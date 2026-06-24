from __future__ import annotations

import os
from src.logger import get_logger

log = get_logger(__name__)


class GeminiSummarizer:

    def __init__(self):
        self._client = None
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            log.warning("GEMINI_API_KEY not set - summaries will be skipped")
            return
        try:
            from google import genai
            self._client = genai.Client(api_key=api_key)
            log.info("Gemini summarizer ready")
        except Exception as e:
            log.warning("Gemini init failed: " + str(e))

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def summarize(self, title: str, body: str) -> str:
        if not self.enabled or not (body or title):
            return ""
        for model in ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-pro"]:
            try:
                text = (body or title)[:4_000]
                prompt = (
                    "You are an expert ESG analyst. Read the following news article and write a thorough summary.\n\n"
                    "Your response must follow this exact format:\n\n"
                    "OVERVIEW\n"
                    "Write 3 to 4 complete sentences explaining what happened, who is involved, and why it matters from an ESG perspective.\n\n"
                    "KEY POINTS\n"
                    "- Point one: a specific fact, number, or action from the article\n"
                    "- Point two: another specific detail or implication\n"
                    "- Point three: the broader ESG significance or impact\n\n"
                    "ESG IMPACT\n"
                    "Write 2 sentences on the real-world ESG implications of this news.\n\n"
                    "Now summarize this article:\n\n"
                    "Title: " + title + "\n\n"
                    "Content: " + text
                )
                response = self._client.models.generate_content(
                    model=model,
                    contents=prompt,
                )
                log.info("Gemini summary generated using " + model)
                return response.text.strip()
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    log.warning(model + " quota exhausted, trying next model")
                    continue
                log.debug("Gemini error on " + model + ": " + err)
                return ""
        log.warning("All Gemini models exhausted quota")
        return ""