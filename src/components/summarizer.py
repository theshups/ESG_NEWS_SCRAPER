from __future__ import annotations
import warnings
import re
warnings.filterwarnings("ignore", category=FutureWarning)
from src.logger import get_logger

log = get_logger(__name__)
MODEL = "falconsai/text_summarization"


class Summarizer:

    def __init__(self):
        self._pipe  = None
        self._tried = False
        self._task  = None

    @property
    def ready(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._tried:
            return
        self._tried = True
        for task in ["summarization", "text2text-generation"]:
            try:
                from transformers import pipeline
                log.info("Loading local AI model: " + MODEL)
                self._pipe = pipeline(task, model=MODEL, device=-1, truncation=True)
                self._task = task
                log.info("Local AI model ready")
                return
            except Exception as e:
                if "Unknown task" in str(e):
                    continue
                log.warning("Could not load model: " + str(e))
                return
        log.warning("No working task found for " + MODEL)

    def summarize(self, title: str, body: str) -> str:
        text = (body or title or "").strip()[:1_024]
        if not text or not self._pipe:
            return ""
        try:
            result = self._pipe(text, max_length=200, min_length=60, do_sample=False, clean_up_tokenization_spaces=True)
            raw = (result[0].get("summary_text") or result[0].get("generated_text") or "").strip()
            return self._format(title, body or text, raw) if raw else ""
        except Exception as e:
            log.warning("Summarizer error: " + str(e))
            return ""

    def _format(self, title: str, body: str, raw: str) -> str:
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
        overview = " ".join(sents[:2]) if len(sents) >= 2 else raw
        points = list(sents[2:])
        if len(points) < 3:
            for s in [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if len(s.strip()) > 40]:
                if s[:140] not in " ".join(points):
                    points.append(s[:140])
                if len(points) >= 3:
                    break
        if not points:
            points = ["Refer to the full article for additional details."]
        esg_impact = sents[-1] if len(sents) >= 3 else "This story carries significant ESG implications."
        out  = "OVERVIEW\n" + overview + "\n\n"
        out += "KEY POINTS\n"
        for p in points[:3]:
            out += "- " + p + "\n"
        out += "\nESG IMPACT\n" + esg_impact
        return out