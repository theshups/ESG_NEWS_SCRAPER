from __future__ import annotations

import random
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings

from src.components.base import BaseScraper
from src.exception import FeedFetchError, FeedParseError
from src.logger import get_logger

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

log = get_logger(__name__)

TIMEOUT   = 25
BODY_CAP  = 8_000
HEADERS   = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control":   "no-cache",
    "Sec-Fetch-Dest":  "document",
    "Sec-Fetch-Mode":  "navigate",
    "Sec-Fetch-Site":  "none",
    "Connection":      "keep-alive",
}


class RSSFeedParser(BaseScraper):

    def __init__(self, config, session: requests.Session = None):
        self.config = config
        self._sess  = session or requests.Session()
        self._sess.headers.update(HEADERS)

    def parse(self) -> list:
        from src.components.scraper import _extract_article, _make_soup
        log.info("[" + self.config.name + "]  requests -> " + self.config.url)
        xml   = self._fetch(self.config.url)
        soup  = _make_soup(xml)
        items = soup.find_all("item") or soup.find_all("entry")

        if not items:
            raise FeedParseError(
                "no items found - site may be blocking requests, try use_browser: true",
                self.config.name,
            )

        fresh, stale = [], 0
        for item in items:
            try:
                art = _extract_article(item, self.config.name, "requests")
                if art is None:
                    continue
                if art.is_stale():
                    stale += 1
                    continue
                if self.config.fetch_full_text and not art.body_text:
                    art.body_text = self._scrape_body(art.url)
                fresh.append(art)
            except Exception as e:
                log.debug("[" + self.config.name + "]  skipped item: " + str(e))

        log.info("[" + self.config.name + "]  " + str(len(fresh)) + " fresh  " + str(stale) + " stale  " + str(len(items)) + " total")
        return fresh

    def _fetch(self, url: str, retries: int = 3) -> str:
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                r = self._sess.get(url, timeout=TIMEOUT, allow_redirects=True)
                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After", 15)) + random.randint(3, 8)
                    log.warning("[" + self.config.name + "]  rate limited, waiting " + str(wait) + "s")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                r.encoding = r.apparent_encoding or "utf-8"
                content = r.text
                is_xml  = "<rss" in content[:1000] or "<feed" in content[:1000] or content.strip().startswith("<?xml")
                is_html = "<html" in content[:300].lower()
                if is_html and not is_xml:
                    raise FeedFetchError(
                        "site returned HTML instead of XML - set use_browser: true in sources.yaml",
                        self.config.name,
                    )
                return content
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_err = e
                if attempt < retries:
                    wait = (2 ** attempt) + random.uniform(0, 2)
                    log.debug("[" + self.config.name + "]  attempt " + str(attempt) + " failed, retry in " + str(round(wait, 1)) + "s")
                    time.sleep(wait)
            except requests.exceptions.HTTPError as e:
                code = e.response.status_code
                if code == 403:
                    raise FeedFetchError("403 Forbidden - set use_browser: true in sources.yaml", self.config.name)
                raise FeedFetchError("HTTP " + str(code), self.config.name)
        raise FeedFetchError("gave up after " + str(retries) + " attempts: " + str(last_err), self.config.name)

    def _scrape_body(self, url: str) -> Optional[str]:
        try:
            time.sleep(random.uniform(2, 4))
            html = self._fetch(url)
            soup = BeautifulSoup(html, "html.parser")
            for junk in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
                junk.decompose()
            text = " ".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
            return text[:BODY_CAP] or None
        except Exception as e:
            log.debug("full-text scrape failed: " + str(e))
            return None