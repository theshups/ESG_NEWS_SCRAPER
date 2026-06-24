import json
import logging
import os
from datetime import datetime


LOG_DIR = "logs"


class _JSONHandler(logging.FileHandler):
    def emit(self, record: logging.LogRecord):
        entry = {
            "timestamp": datetime.utcfromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = logging.Formatter().formatException(record.exc_info)
        try:
            self.stream.write(json.dumps(entry) + "\n")
            self.flush()
        except Exception:
            self.handleError(record)


def get_logger(name: str) -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")

    log = logging.getLogger(name)
    if log.handlers:
        return log

    log.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  -  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(f"{LOG_DIR}/esg_{today}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    jh = _JSONHandler(f"{LOG_DIR}/esg_{today}.jsonl", encoding="utf-8")
    jh.setLevel(logging.INFO)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    log.addHandler(fh)
    log.addHandler(jh)
    log.addHandler(ch)
    log.propagate = False
    return log


def export_logs_json(output_path: str = None) -> str:
    os.makedirs(LOG_DIR, exist_ok=True)
    entries = []

    jsonl_files = sorted(
        f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl")
    )
    for fname in jsonl_files:
        with open(os.path.join(LOG_DIR, fname), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    if not output_path:
        output_path = os.path.join(
            LOG_DIR, f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    return output_path
