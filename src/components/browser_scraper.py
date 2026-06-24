from __future__ import annotations

from bs4 import BeautifulSoup
from datetime import datetime, timezone

from src.components.base import BaseScraper
from src.exception import BrowserError
from src.logger import get_logger

log = get_logger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
}


class BrowserFeedParser(BaseScraper):

    def __init__(self, config):
        self.config = config

    def parse(self) -> list:
        from src.components.scraper import _extract_article, _make_soup, Article
        log.info("[" + self.config.name + "]  chromium -> " + self.config.url)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserError(
                "playwright not installed - run: pip install playwright && playwright install chromium",
                self.config.name,
            )

        content = None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
                )
                ctx = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="en-US",
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()
                page.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4,mp3}",
                    lambda route: route.abort(),
                )
                page.goto(self.config.url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2_000)
                content = page.content()
                browser.close()
        except Exception as e:
            raise BrowserError("chromium failed: " + str(e), self.config.name)

        soup  = _make_soup(content)
        items = soup.find_all("item") or soup.find_all("entry")

        if not items:
            return self._scrape_cards(content)

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
                log.debug("[" + self.config.name + "]  skipped item: " + str(e))

        log.info("[" + self.config.name + "]  " + str(len(fresh)) + " fresh  " + str(stale) + " stale  " + str(len(items)) + " total (browser)")
        return fresh

    def _scrape_cards(self, html: str) -> list:
        from src.components.scraper import Article
        soup   = BeautifulSoup(html, "html.parser")
        result = []
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        for a in soup.find_all("a", href=True):
            href  = a.get("href", "").strip()
            title = a.get_text(strip=True)
            if not title or len(title) < 40:
                continue
            if not href.startswith("http"):
                continue
            if any(s in href for s in ["/tag/", "/category/", "/author/", "#"]):
                continue
            result.append(Article(
                title=title,
                url=href,
                published_date=datetime.now(timezone.utc),
                source_name=self.config.name,
                fetched_via="browser",
            ))
            if len(result) >= 15:
                break
        log.info("[" + self.config.name + "]  " + str(len(result)) + " articles scraped from page (browser fallback)")
        return result