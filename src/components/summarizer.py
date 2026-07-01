from __future__ import annotations
import re, requests, os
from src.logger import get_logger

log = get_logger(__name__)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

PREFERRED_MODELS = ["qwen2.5:1.5b", "qwen2.5:3b", "phi3.5:latest", "phi3.5"]

SUMMARY_PROMPT = """Summarize this ESG article in exactly this format. Be specific with names, numbers, regulations. Do not repeat these instructions back.

OVERVIEW
2-3 sentences: what happened, who is involved, why it matters for ESG/carbon compliance.

KEY POINTS
- one specific fact from the article
- one business implication
- one regulatory or ESG significance

ESG IMPACT
1-2 sentences on what this means for businesses doing carbon accounting or sustainability reporting.

Title: {{TITLE}}
Article: {{CONTENT}}"""


class Summarizer:

    def __init__(self):
        self._model = None
        self._ready = False
        self._tried = False
        self._session = requests.Session()

    @property
    def ready(self) -> bool:
        return self._ready

    def load(self) -> None:
        if self._tried:
            return
        self._tried = True
        try:
            r = self._session.get(OLLAMA_HOST + "/api/tags", timeout=5)
            if r.status_code != 200:
                return
            models = [m["name"] for m in r.json().get("models", [])]
            if not models:
                return
            self._model = models[0]
            for p in PREFERRED_MODELS:
                if p in models:
                    self._model = p
                    break
            self._ready = True
            log.info("Summarizer ready via Ollama: " + self._model)
        except Exception as e:
            log.warning("Summarizer init failed: " + str(e))

    def summarize(self, title: str, body: str) -> str:
        if not self._ready or not self._model:
            return ""
        content = (body or "").strip()
        if len(content) < 50:
            content = (title or "").strip()
        if not content:
            return ""
        content = content[:1_000]
        prompt = SUMMARY_PROMPT.replace("{{TITLE}}", (title or "")[:200]).replace("{{CONTENT}}", content)
        try:
            resp = self._session.post(
                OLLAMA_HOST + "/api/generate",
                json={
                    "model": self._model, "prompt": prompt, "stream": False, "think": False,
                    "options": {"temperature": 0.3, "num_predict": 350},
                },
                timeout=90,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            raw = re.sub(r"</?think>", "", raw).strip()
            if not raw or "OVERVIEW" not in raw.upper():
                log.warning("Malformed summary, retrying once with shorter input")
                return self._retry_short(title, body)
            log.info("Summary generated: " + self._model)
            return raw.strip()
        except requests.exceptions.Timeout:
            log.warning("Summarizer timed out")
            return ""
        except Exception as e:
            log.warning("Summarizer error: " + str(e)[:80])
            return ""

    def _retry_short(self, title: str, body: str) -> str:
        """One retry with a much shorter prompt for weak models."""
        content = (body or title or "")[:400]
        prompt = "Summarize in 3 short sentences for an ESG business audience:\n\n" + content
        try:
            resp = self._session.post(
                OLLAMA_HOST + "/api/generate",
                json={"model": self._model, "prompt": prompt, "stream": False, "think": False,
                      "options": {"temperature": 0.3, "num_predict": 150}},
                timeout=60,
            )
            raw = resp.json().get("response", "")
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            return ("OVERVIEW\n" + raw.strip()) if raw.strip() else ""
        except Exception:
            return ""