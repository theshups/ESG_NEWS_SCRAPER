from __future__ import annotations
import random
import time
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup

from src.components.base import BaseScraper
from src.exception import BrowserError
from src.logger import get_logger

log = get_logger(__name__)

# realistic user agents — rotated randomly each request
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

# realistic viewport sizes
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 800},
]


class StealthScraper(BaseScraper):
    """
    Playwright Chromium with stealth plugin and anti-fingerprint configuration.

    Extends BaseScraper — overrides parse().

    Use when:
      - Regular BrowserFeedParser still gets blocked
      - Site uses Cloudflare Bot Management
      - Site checks navigator.webdriver
      - Site uses canvas/WebGL fingerprinting
      - Site requires realistic human-like behaviour

    Set in sources.yaml:
      use_stealth: true
    """

    def __init__(self, config):
        self.config = config

    def parse(self) -> list:                          # override BaseScraper
        from src.components.scraper import _extract_article, _make_soup, Article

        log.info("[" + self.config.name + "]  stealth chromium -> " + self.config.url)

        # check playwright is installed
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserError(
                "playwright not installed — run: pip install playwright && playwright install chromium",
                self.config.name,
            )

        # check stealth is installed
        try:
            from playwright_stealth import stealth_sync  # type: ignore[import]
        except ImportError:
            raise BrowserError(
                "playwright-stealth not installed — run: pip install playwright-stealth",
                self.config.name,
            )

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
                        "--disable-blink-features=AutomationControlled",  # key stealth flag
                        "--disable-web-security",
                        "--disable-features=VizDisplayCompositor",
                        "--window-size=" + str(viewport["width"]) + "," + str(viewport["height"]),
                    ],
                )

                ctx = browser.new_context(
                    user_agent=ua,
                    viewport=viewport,
                    locale="en-US",
                    timezone_id="America/New_York",
                    extra_http_headers={
                        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                        "Sec-Fetch-Dest":  "document",
                        "Sec-Fetch-Mode":  "navigate",
                        "Sec-Fetch-Site":  "none",
                        "Sec-Fetch-User":  "?1",
                        "Upgrade-Insecure-Requests": "1",
                        "DNT": "1",
                    },
                )

                page = ctx.new_page()

                # apply stealth patches — this is the key part
                # patches: navigator.webdriver, plugins, languages,
                # permissions, chrome runtime, iframe contentWindow,
                # media codecs, webgl vendor, canvas fingerprint
                stealth_sync(page)

                # block heavy assets — we only need text
                page.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,eot,mp4,mp3,wav}",
                    lambda route: route.abort(),
                )

                # human-like: slight random delay before navigating
                time.sleep(random.uniform(0.5, 1.5))

                page.goto(
                    self.config.url,
                    wait_until="domcontentloaded",
                    timeout=40_000,
                )

                # human-like: random wait after load
                page.wait_for_timeout(random.randint(1_500, 3_500))

                # check for captcha — if found, log and bail
                html_preview = page.content()[:2000].lower()
                if any(word in html_preview for word in ["captcha", "cf-challenge", "checking your browser", "ray id"]):
                    log.warning("[" + self.config.name + "]  captcha detected — stealth bypassed, skipping")
                    browser.close()
                    return []

                content = page.content()
                browser.close()

        except Exception as e:
            raise BrowserError("stealth chromium failed: " + str(e), self.config.name)

        # parse the content
        soup  = _make_soup(content)
        items = soup.find_all("item") or soup.find_all("entry")

        if not items:
            # fallback: scrape article links from the page
            return self._scrape_links(content)

        fresh, stale = [], 0
        for item in items:
            try:
                art = _extract_article(item, self.config.name, "stealth")
                if art is None:
                    continue
                if art.is_stale():
                    stale += 1
                    continue
                fresh.append(art)
            except Exception as e:
                log.debug("[" + self.config.name + "]  skipped item: " + str(e))

        log.info(
            "[" + self.config.name + "]  "
            + str(len(fresh)) + " fresh  "
            + str(stale) + " stale  "
            + str(len(items)) + " total (stealth)"
        )
        return fresh

    def _scrape_links(self, html: str) -> list:
        """
        Fallback when no RSS tags found.
        Extracts article links from a rendered page.
        """
        from src.components.scraper import Article

        soup   = BeautifulSoup(html, "html.parser")
        result = []

        # remove navigation noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        for a in soup.find_all("a", href=True):
            href  = a.get("href", "").strip()
            title = a.get_text(strip=True)

            if not title or len(title) < 40:
                continue
            if not href.startswith("http"):
                continue
            if any(s in href for s in ["/tag/", "/category/", "/author/", "/page/", "#", "?", "javascript"]):
                continue

            result.append(Article(
                title=title,
                url=href,
                published_date=datetime.now(timezone.utc),
                source_name=self.config.name,
                fetched_via="stealth",
            ))

            if len(result) >= 20:
                break

        log.info("[" + self.config.name + "]  " + str(len(result)) + " links scraped (stealth fallback)")
        return result