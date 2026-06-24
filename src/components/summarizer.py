from __future__ import annotations
import re
from src.logger import get_logger

log = get_logger(__name__)
MODEL = "falconsai/text_summarization"


class Summarizer:

    def __init__(self):
        self._pipe  = None
        self._tried = False

    @property
    def ready(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._tried:
            return
        self._tried = True

        # try each task name in order until one works
        for task in ["summarization", "text2text-generation"]:
            try:
                from transformers import pipeline
                log.info("Loading local AI model with task=" + task)
                self._pipe = pipeline(
                    task,
                    model=MODEL,
                    device=-1,
                    truncation=True,
                )
                log.info("Local AI model ready (task=" + task + ")")
                self._task = task
                return
            except Exception as e:
                err = str(e)
                if "Unknown task" in err or "available tasks" in err:
                    log.debug("Task " + task + " not available, trying next")
                    continue
                log.warning("Could not load model: " + err)
                return

        log.warning("No working task found for " + MODEL)

    def summarize(self, title: str, body: str) -> str:
        text = (body or "").strip()
        if len(text) < 50:
            text = (title or "").strip()
        if not text or not self._pipe:
            return ""

        text = text[:1_024]

        try:
            result = self._pipe(
                text,
                max_length=200,
                min_length=60,
                do_sample=False,
                clean_up_tokenization_spaces=True,
            )
            # both tasks return list of dicts but with different keys
            raw = (
                result[0].get("summary_text") or
                result[0].get("generated_text") or ""
            ).strip()
            if not raw:
                return ""
            return self._format(title, body or text, raw)
        except Exception as e:
            log.warning("Summarizer error: " + str(e))
            return ""

    def _format(self, title: str, body: str, raw: str) -> str:
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
        overview = " ".join(sents[:2]) if len(sents) >= 2 else raw

        points = list(sents[2:])
        if len(points) < 3:
            body_sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if len(s.strip()) > 40]
            for s in body_sents:
                if s[:140] not in " ".join(points):
                    points.append(s[:140])
                if len(points) >= 3:
                    break
        if not points:
            points = ["Refer to the full article for additional details."]

        esg_impact = sents[-1] if len(sents) >= 3 else (
            "This story carries significant implications for ESG compliance, "
            "sustainability strategy, and stakeholder reporting."
        )

        out  = "OVERVIEW\n" + overview + "\n\n"
        out += "KEY POINTS\n"
        for p in points[:3]:
            out += "- " + p + "\n"
        out += "\nESG IMPACT\n" + esg_impact
        return out