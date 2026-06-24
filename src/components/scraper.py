from __future__ import annotations

import hashlib
import random
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from src.components.base import BaseScraper
from src.exception import BrowserError, FeedFetchError, FeedParseError
from src.logger import get_logger

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

log = get_logger(__name__)

FRESH_DAYS = 7
TIMEOUT    = 25
DELAY_MIN  = 2.0
DELAY_MAX  = 5.0
BODY_CAP   = 8_000

# full chrome fingerprint so sites don't block us immediately
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept":           "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language":  "en-US,en;q=0.9",
    "Accept-Encoding":  "gzip, deflate, br",
    "Cache-Control":    "no-cache",
    "Pragma":           "no-cache",
    "Sec-Fetch-Dest":   "document",
    "Sec-Fetch-Mode":   "navigate",
    "Sec-Fetch-Site":   "none",
    "Upgrade-Insecure-Requests": "1",
    "Connection":       "keep-alive",
}


# --------------------------------------------------------------------------- #
#  Article — data carrier through the whole pipeline                           #
# --------------------------------------------------------------------------- #

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
        self.article_id = hashlib.md5(self.url.encode()).hexdigest()

    def is_stale(self) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=FRESH_DAYS)
        pub = self.published_date
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        return pub < cutoff

    def text_for_classifier(self) -> str:
        # prefer body, fall back to title — classifier needs something to work with
        return (self.body_text or self.title or "")[:1_024]

    def __str__(self):
        cat = f" [{self.esg_category}]" if self.esg_category else ""
        return f"{self.source_name}{cat} — {self.title[:70]}"


@dataclass
class FeedConfig:
    name:            str
    url:             str
    use_browser:     bool = False   # True = Playwright Chromium
    fetch_full_text: bool = False


# --------------------------------------------------------------------------- #
#  Shared XML parsing helpers (used by both scrapers)                          #
# --------------------------------------------------------------------------- #

def _make_soup(content: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(content, "lxml-xml")   # best for RSS namespaces
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
        return parsedate_to_datetime(raw)           # RFC 2822 (standard RSS)
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _extract_article(item, source_name: str, fetched_via: str = "requests") -> Optional[Article]:
    """
    Pull all fields out of one <item> or <entry> tag.
    Handles RSS 2.0, Atom, dc: namespace, CDATA, and minimal feeds.
    """
    # title
    t     = item.find("title")
    title = t.get_text(strip=True) if t else "Untitled"

    # url — RSS puts it in <link> text, Atom puts it in <link href="...">
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

    # date — try all common tag names
    date_tag = (
        item.find("pubDate") or item.find("pubdate") or
        item.find("published") or item.find("updated") or
        item.find("dc:date") or item.find("date")
    )
    pub_date = _parse_date(date_tag.get_text(strip=True) if date_tag else None)
    if pub_date is None:
        pub_date = datetime.now(timezone.utc)

    # author — Atom wraps in <author><name>...</name></author>
    author     = None
    author_tag = item.find("author") or item.find("dc:creator") or item.find("creator")
    if author_tag:
        inner  = author_tag.find("name")
        author = inner.get_text(strip=True) if inner else _clean_text(author_tag.get_text())

    # body — prefer full encoded content over summary
    body_tag = (
        item.find("content:encoded") or
        item.find("description") or
        item.find("summary") or
        item.find("content")
    )
    body = None
    if body_tag:
        body = _clean_text(body_tag.get_text(separator=" ", strip=True))
        if body:
            body = body[:BODY_CAP]

    return Article(
        title=title, url=url, published_date=pub_date,
        source_name=source_name, author=author,
        body_text=body, fetched_via=fetched_via,
    )


# --------------------------------------------------------------------------- #
#  RSSFeedParser — BeautifulSoup over requests (fast, lightweight)             #
# --------------------------------------------------------------------------- #

class RSSFeedParser(BaseScraper):

    def __init__(self, config: FeedConfig, session: requests.Session = None):
        self.config = config
        self._sess  = session or requests.Session()
        self._sess.headers.update(HEADERS)

    def parse(self) -> list[Article]:          # override
        log.info(f"[{self.config.name}]  requests → {self.config.url}")
        xml   = self._fetch(self.config.url)
        soup  = _make_soup(xml)
        items = soup.find_all("item") or soup.find_all("entry")

        if not items:
            raise FeedParseError(
                "no <item>/<entry> tags found — "
                "feed may have returned a login page or captcha instead of XML",
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
                log.debug(f"[{self.config.name}]  skipped item: {e}")

        log.info(f"[{self.config.name}]  {len(fresh)} fresh  {stale} stale  {len(items)} total")
        return fresh

    def _fetch(self, url: str, retries: int = 3) -> str:
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                r = self._sess.get(url, timeout=TIMEOUT, allow_redirects=True)

                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After", 15)) + random.randint(3, 8)
                    log.warning(f"[{self.config.name}]  rate limited — waiting {wait}s")
                    time.sleep(wait)
                    continue

                r.raise_for_status()
                r.encoding = r.apparent_encoding or "utf-8"
                content    = r.text

                # if we got an HTML page instead of XML, the site blocked us
                is_xml  = "<rss" in content[:1000] or "<feed" in content[:1000] or content.strip().startswith("<?xml")
                is_html = "<html" in content[:300].lower()
                if is_html and not is_xml:
                    raise FeedFetchError(
                        "got HTML instead of XML — site is blocking requests. "
                        "set use_browser: true in sources.yaml for this feed.",
                        self.config.name,
                    )
                return content

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_err = e
                if attempt < retries:
                    wait = (2 ** attempt) + random.uniform(0, 2)
                    log.debug(f"[{self.config.name}]  attempt {attempt} failed, retry in {wait:.1f}s")
                    time.sleep(wait)

            except requests.exceptions.HTTPError as e:
                code = e.response.status_code
                if code == 403:
                    raise FeedFetchError(
                        "403 Forbidden — set use_browser: true in sources.yaml for this feed",
                        self.config.name,
                    )
                raise FeedFetchError(f"HTTP {code}", self.config.name)

        raise FeedFetchError(f"gave up after {retries} attempts: {last_err}", self.config.name)

    def _scrape_body(self, url: str) -> Optional[str]:
        try:
            _sleep()
            html = self._fetch(url)
            soup = BeautifulSoup(html, "html.parser")
            for junk in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
                junk.decompose()
            paragraphs = soup.find_all("p")
            text = " ".join(p.get_text(" ", strip=True) for p in paragraphs)
            return text[:BODY_CAP] or None
        except Exception as e:
            log.debug(f"full-text scrape failed for {url}: {e}")
            return None


# --------------------------------------------------------------------------- #
#  BrowserFeedParser — Playwright Chromium for blocked / JS-heavy sites        #
#                                                                              #
#  Use this when:                                                              #
#   • The site returns 403 to Python requests                                  #
#   • The site requires JS to render the RSS or article list                   #
#   • Set use_browser: true in sources.yaml                                   #
# --------------------------------------------------------------------------- #

class BrowserFeedParser(BaseScraper):

    def __init__(self, config: FeedConfig):
        self.config = config

    def parse(self) -> list[Article]:          # override
        log.info(f"[{self.config.name}]  chromium → {self.config.url}")
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
        except ImportError:
            raise BrowserError(
                "playwright is not installed — run: pip install playwright && playwright install chromium",
                self.config.name,
            )

        content = None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
                ctx  = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="en-US",
                    viewport={"width": 1280, "height": 800},
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                    },
                )
                page = ctx.new_page()

                # block images/fonts/media — we only need text content
                page.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4,mp3}",
                    lambda route: route.abort(),
                )

                page.goto(self.config.url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2_000)    # let any lazy-loaded JS finish
                content = page.content()
                browser.close()

        except Exception as e:
            raise BrowserError(f"chromium failed: {e}", self.config.name)

        soup  = _make_soup(content)
        items = soup.find_all("item") or soup.find_all("entry")

        # if it's not an RSS feed, try to scrape article cards from the page
        if not items:
            return self._scrape_article_cards(content)

        fresh, stale = [], 0
        for item in items:
            try:
                art = _extract_article(item, self.config.name, "browser")
                if art is None:
                    continue
                if art.is_stale():
                    stale += 1
                    continue
                fresh.append(art)
            except Exception as e:
                log.debug(f"[{self.config.name}]  skipped item: {e}")

        log.info(f"[{self.config.name}]  {len(fresh)} fresh  {stale} stale  {len(items)} total (browser)")
        return fresh

    def _scrape_article_cards(self, html: str) -> list[Article]:
        """
        Fallback for non-RSS pages — find article headlines and links
        from rendered HTML. Works for news homepages and article listings.
        """
        soup   = BeautifulSoup(html, "html.parser")
        result = []

        # remove junk regions
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # find all <a> tags that look like article links
        for a in soup.find_all("a", href=True):
            href  = a.get("href", "").strip()
            title = a.get_text(strip=True)

            if not title or len(title) < 20:
                continue
            if not href.startswith("http"):
                continue
            # skip nav links, category pages, etc.
            if any(skip in href for skip in ["/tag/", "/category/", "/author/", "#", "?"]):
                continue

            result.append(Article(
                title=title, url=href,
                published_date=datetime.now(timezone.utc),
                source_name=self.config.name,
                fetched_via="browser",
            ))

            if len(result) >= 15:
                break

        log.info(f"[{self.config.name}]  {len(result)} articles scraped from page (browser fallback)")
        return result


# --------------------------------------------------------------------------- #
#  ESGScraper — orchestrates all feeds, picks the right parser per feed        #
# --------------------------------------------------------------------------- #

class ESGScraper(BaseScraper):

    def __init__(self, feeds: list[FeedConfig]):
        self._feeds   = feeds
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self.results: list[Article] = []

    def parse(self) -> list[Article]:          # override
        all_articles = []

        for i, config in enumerate(self._feeds):
            try:
                if config.use_browser:
                    parser = BrowserFeedParser(config)
                else:
                    parser = RSSFeedParser(config, session=self._session)

                all_articles.extend(parser.parse())

            except FeedFetchError as e:
                log.error(f"fetch failed — {e}")
            except FeedParseError as e:
                log.error(f"parse failed — {e}")
            except BrowserError as e:
                log.error(f"browser failed — {e}")
            except Exception as e:
                log.exception(f"unexpected error on {config.name}: {e}")

            if i < len(self._feeds) - 1:
                _sleep()

        return all_articles

    def run(self) -> list[Article]:            # override
        log.info(f"starting scrape — {len(self._feeds)} feeds configured")
        self.results = self.parse()
        log.info(f"scrape done — {len(self.results)} fresh articles")
        return self.results


def _sleep():
    delay = random.uniform(DELAY_MIN, DELAY_MAX)
    log.debug(f"politeness delay {delay:.1f}s")
    time.sleep(delay)
