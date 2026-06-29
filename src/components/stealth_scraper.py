from __future__ import annotations
import random, time
from datetime import datetime, timezone
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from src.components.base import BaseScraper
from src.exception import BrowserError
from src.logger import get_logger

log = get_logger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
]

SKIP_PATTERNS = [
    "/tag/", "/tags/", "/category/", "/author/", "/page/",
    "/about/", "/contact/", "/subscribe/", "/newsletter/",
    "javascript:", "mailto:", "?s=",
]


def _get_stealth():
    try:
        from playwright_stealth import Stealth
        s = Stealth()
        if hasattr(s, "apply_stealth_sync"):
            return lambda page: s.apply_stealth_sync(page)
        elif hasattr(s, "stealth_sync"):
            return lambda page: s.stealth_sync(page)
    except Exception:
        pass
    try:
        from playwright_stealth import stealth
        return lambda page: stealth(page)
    except Exception:
        pass
    return None


class StealthScraper(BaseScraper):

    def __init__(self, config):
        self.config = config
        self._base  = urlparse(config.url).scheme + "://" + urlparse(config.url).netloc

    def parse(self) -> list:
        from src.components.scraper import _extract_article, _make_soup, Article
        log.info("[" + self.config.name + "]  stealth -> " + self.config.url)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserError("playwright not installed", self.config.name)

        stealth_fn = _get_stealth()
        if stealth_fn:
            log.debug("[" + self.config.name + "]  stealth patches active")
        else:
            log.warning("[" + self.config.name + "]  stealth unavailable — running as regular browser")

        ua       = random.choice(USER_AGENTS)
        viewport = random.choice(VIEWPORTS)
        content  = None

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                ctx = browser.new_context(
                    user_agent=ua,
                    viewport=viewport,
                    locale="en-US",
                    extra_http_headers={
                        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                        "DNT":             "1",
                    },
                )
                page = ctx.new_page()

                if stealth_fn:
                    stealth_fn(page)

                page.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4,mp3,ico}",
                    lambda route: route.abort(),
                )

                time.sleep(random.uniform(0.5, 1.5))

                try:
                    page.goto(self.config.url, wait_until="domcontentloaded", timeout=40_000)
                except Exception:
                    page.goto(self.config.url, wait_until="load", timeout=50_000)

                page.wait_for_timeout(random.randint(2_000, 3_500))

                preview = page.content()[:2000].lower()
                if any(w in preview for w in ["captcha", "cf-challenge", "checking your browser"]):
                    log.warning("[" + self.config.name + "]  captcha detected — skipping")
                    browser.close()
                    return []

                content = page.content()
                browser.close()

        except BrowserError:
            raise
        except Exception as e:
            raise BrowserError("stealth failed: " + str(e), self.config.name)

        soup  = _make_soup(content)
        items = soup.find_all("item") or soup.find_all("entry")

        if items:
            fresh, stale = [], 0
            for item in items:
                try:
                    art = _extract_article(item, self.config.name, "stealth")
                    if art is None: continue
                    if art.is_stale(): stale += 1; continue
                    fresh.append(art)
                except Exception:
                    continue
            log.info("[" + self.config.name + "]  " + str(len(fresh)) + " fresh  " + str(stale) + " stale  (stealth)")
            return fresh

        return self._extract_links(content)

    def _extract_links(self, html: str) -> list:
        from src.components.scraper import Article
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script","style","nav","footer","header","aside","form","iframe"]):
            tag.decompose()

        seen, result = set(), []
        for a in soup.find_all("a", href=True):
            href  = a.get("href","").strip()
            title = a.get_text(strip=True)
            if not href or not title or len(title) < 30: continue
            if href.startswith("/"): href = self._base + href
            if not href.startswith("http"): continue
            if any(s in href for s in SKIP_PATTERNS): continue
            if self._base.replace("https://","").replace("http://","") not in href: continue
            if href in seen: continue
            seen.add(href)
            result.append(Article(
                title=title, url=href,
                published_date=datetime.now(timezone.utc),
                source_name=self.config.name,
                fetched_via="stealth",
            ))
            if len(result) >= 20: break

        log.info("[" + self.config.name + "]  " + str(len(result)) + " links (stealth fallback)")
        return result