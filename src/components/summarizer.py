from __future__ import annotations
import re, requests, os
from src.logger import get_logger

log = get_logger(__name__)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

SUMMARY_PROMPT = """/no_think
Summarize this ESG news article in three sections. Be specific — include company names, numbers, regulations.

Title: {{TITLE}}
Content: {{CONTENT}}

OVERVIEW
2-3 sentences on what happened, who is involved, and why it matters for carbon management and ESG compliance.

KEY POINTS
- First specific fact, number, or policy name from the article
- Second key detail or business implication
- Third ESG significance or regulatory impact

ESG IMPACT
1-2 sentences on real-world implications for businesses in carbon management and sustainability reporting."""


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
                log.warning("Ollama not available for summarization")
                return
            models = [m["name"] for m in r.json().get("models", [])]
            if not models:
                return
            preferred = ["qwen2.5:1.5b","phi3.5:latest","phi3.5","qwen2.5:3b","qwen2.5:latest"]
            self._model = models[0]
            for p in preferred:
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

        # use body if available otherwise title only
        content = (body or "").strip()
        if len(content) < 50:
            content = (title or "").strip()
        if not content:
            return ""

        content = content[:1_200]
        prompt  = SUMMARY_PROMPT.replace("{{TITLE}}", (title or "")[:200]).replace("{{CONTENT}}", content)

        try:
            resp = self._session.post(
                OLLAMA_HOST + "/api/generate",
                json={
                    "model":  self._model,
                    "prompt": prompt,
                    "stream": False,
                    "think":  False,
                    "options": {"temperature": 0.3, "num_predict": 400},
                },
                timeout=180,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            raw = re.sub(r"</?think>", "", raw).strip()
            if not raw:
                log.warning("Empty summary response")
                return ""
            log.info("Summary generated via Ollama: " + self._model)
            return raw.strip()
        except requests.exceptions.Timeout:
            log.warning("Summarizer timed out")
            return ""
        except Exception as e:
            log.warning("Summarizer error: " + str(e)[:80])
            return ""