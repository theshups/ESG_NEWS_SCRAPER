from __future__ import annotations

import hashlib
import random
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from src.components.base import BaseScraper
from src.exception import BrowserError, FeedFetchError, FeedParseError
from src.logger import get_logger

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
log = get_logger(__name__)

FRESH_DAYS = 7
DELAY_MIN  = 2.0
DELAY_MAX  = 5.0


@dataclass
class Article:
    title:          str
    url:            str
    published_date: datetime
    source_name:    str
    author:         Optional[str]  = None
    body_text:      Optional[str]  = None
    esg_category:   Optional[str]  = None
    confidence:     Optional[float] = None
    fetched_via:    str            = "requests"
    article_id: str = field(init=False, repr=False)

    def __post_init__(self):
        self.url = self.url.strip().rstrip("/")
        self.article_id = hashlib.md5(self.url.encode()).hexdigest()

    def is_stale(self) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=FRESH_DAYS)
        pub = self.published_date
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        return pub < cutoff

    def text_for_classifier(self) -> str:
        return (self.body_text or self.title or "")[:1_024]

    def __str__(self):
        return self.source_name + " - " + self.title[:70]


@dataclass
class FeedConfig:
    name:            str
    url:             str
    use_browser:     bool = False
    fetch_full_text: bool = False


def _make_soup(content: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(content, "lxml-xml")
    except Exception:
        return BeautifulSoup(content, "html.parser")


def _clean_text(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = BeautifulSoup(raw, "html.parser").get_text(separator=" ")
    return " ".join(text.split()) or None


def _parse_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    raw = raw.strip()
    try:
        return parsedate_to_datetime(raw)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _extract_article(item, source_name: str, fetched_via: str = "requests") -> Optional[Article]:
    t     = item.find("title")
    title = t.get_text(strip=True) if t else "Untitled"

    url  = ""
    link = item.find("link")
    if link:
        url = link.get("href", "").strip() or link.get_text(strip=True)
    if not url:
        guid = item.find("guid")
        if guid and guid.get("isPermaLink", "true").lower() != "false":
            url = guid.get_text(strip=True)
    if not url:
        return None

    date_tag = (
        item.find("pubDate") or item.find("pubdate") or
        item.find("published") or item.find("updated") or
        item.find("dc:date") or item.find("date")
    )
    pub_date = _parse_date(date_tag.get_text(strip=True) if date_tag else None)
    if pub_date is None:
        pub_date = datetime.now(timezone.utc)

    author     = None
    author_tag = item.find("author") or item.find("dc:creator") or item.find("creator")
    if author_tag:
        inner  = author_tag.find("name")
        author = inner.get_text(strip=True) if inner else _clean_text(author_tag.get_text())

    body_tag = (
        item.find("content:encoded") or item.find("description") or
        item.find("summary") or item.find("content")
    )
    body = None
    if body_tag:
        body = _clean_text(body_tag.get_text(separator=" ", strip=True))
        if body:
            body = body[:8_000]

    return Article(
        title=title, url=url, published_date=pub_date,
        source_name=source_name, author=author,
        body_text=body, fetched_via=fetched_via,
    )


class ESGScraper(BaseScraper):

    def __init__(self, feeds: list):
        self._feeds   = feeds
        self.results  = []

    def parse(self) -> list:
        import requests as req
        from src.components.rss_scraper import RSSFeedParser, HEADERS
        from src.components.browser_scraper import BrowserFeedParser

        session = req.Session()
        session.headers.update(HEADERS)
        all_articles = []

        for i, config in enumerate(self._feeds):
            try:
                if config.use_browser:
                    parser = BrowserFeedParser(config)
                else:
                    parser = RSSFeedParser(config, session=session)
                all_articles.extend(parser.parse())
            except FeedFetchError as e:
                log.error("fetch failed - " + str(e))
            except FeedParseError as e:
                log.error("parse failed - " + str(e))
            except BrowserError as e:
                log.error("browser failed - " + str(e))
            except Exception as e:
                log.exception("unexpected on " + config.name + ": " + str(e))
            if i < len(self._feeds) - 1:
                delay = random.uniform(DELAY_MIN, DELAY_MAX)
                log.debug("politeness delay " + str(round(delay, 1)) + "s")
                time.sleep(delay)

        seen, unique = set(), []
        for a in all_articles:
            if a.article_id not in seen:
                seen.add(a.article_id)
                unique.append(a)
        if len(all_articles) != len(unique):
            log.info("deduplication removed " + str(len(all_articles) - len(unique)) + " cross-feed duplicates")

        return unique

    def run(self) -> list:
        log.info("starting scrape - " + str(len(self._feeds)) + " feeds configured")
        self.results = self.parse()
        log.info("scrape done - " + str(len(self.results)) + " unique fresh articles")
        return self.results