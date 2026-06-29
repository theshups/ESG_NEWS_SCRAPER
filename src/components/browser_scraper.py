from __future__ import annotations
import time, random
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from src.components.base import BaseScraper
from src.exception import BrowserError
from src.logger import get_logger

log = get_logger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

COOKIE_SELECTORS = [
    "button#onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "button.cookie-consent-accept",
    "button[data-testid='accept-button']",
    "button[aria-label='Accept all']",
    "button[aria-label='Accept cookies']",
    "a.cc-btn.cc-allow",
    ".cookie-notice button",
    "#accept-all-cookies",
    "button.js-accept-cookies",
    "button.gdpr-accept",
    "[data-action='accept']",
]

SKIP_PATTERNS = [
    "/tag/", "/tags/", "/category/", "/categories/",
    "/author/", "/authors/", "/page/", "/about/",
    "/contact/", "/advertise/", "/subscribe/",
    "/newsletter/", "/podcast/", "/video/", "/videos/",
    "javascript:", "mailto:", "#", "?s=",
]

ARTICLE_PATTERNS = [
    "/article/", "/story/", "/news/", "/post/", "/blog/",
    "/report/", "/analysis/", "/feature/", "/opinion/",
    "/energy/", "/climate/", "/environment/", "/sustainability/",
    "/section/", "/guides/",
]


class BrowserFeedParser(BaseScraper):

    def __init__(self, config):
        self.config = config
        self._base_url = self._get_base(config.url)

    def _get_base(self, url: str) -> str:
        p = urlparse(url)
        return p.scheme + "://" + p.netloc

    def parse(self) -> list:
        from src.components.scraper import _extract_article, _make_soup
        log.info("[" + self.config.name + "]  browser -> " + self.config.url)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserError("playwright not installed", self.config.name)

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
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                ctx = browser.new_context(
                    user_agent=UA,
                    locale="en-US",
                    viewport={"width": 1280, "height": 800},
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )
                page = ctx.new_page()

                # block heavy assets for speed
                page.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4,mp3,ico}",
                    lambda route: route.abort(),
                )

                # load page
                try:
                    page.goto(self.config.url, wait_until="domcontentloaded", timeout=40_000)
                except Exception:
                    try:
                        page.goto(self.config.url, wait_until="load", timeout=50_000)
                    except Exception as e:
                        raise BrowserError("page load failed: " + str(e), self.config.name)

                page.wait_for_timeout(3_000)

                # dismiss cookie banners
                for sel in COOKIE_SELECTORS:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=800):
                            btn.click()
                            page.wait_for_timeout(1_200)
                            log.debug("[" + self.config.name + "]  cookie banner dismissed")
                            break
                    except Exception:
                        continue

                # scroll to trigger lazy loading
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                    page.wait_for_timeout(1_500)
                except Exception:
                    pass

                content = page.content()
                browser.close()

        except BrowserError:
            raise
        except Exception as e:
            raise BrowserError("chromium error: " + str(e), self.config.name)

        # try RSS/Atom parsing first
        soup  = _make_soup(content)
        items = soup.find_all("item") or soup.find_all("entry")

        if items:
            from src.components.scraper import _extract_article
            fresh, stale = [], 0
            for item in items:
                try:
                    art = _extract_article(item, self.config.name, "browser")
                    if art is None: continue
                    if art.is_stale(): stale += 1; continue
                    fresh.append(art)
                except Exception:
                    continue
            log.info("[" + self.config.name + "]  " + str(len(fresh)) + " fresh  " + str(stale) + " stale  " + str(len(items)) + " total")
            return fresh

        # fallback: extract article links from HTML
        return self._extract_links(content)

    def _extract_links(self, html: str) -> list:
        from src.components.scraper import Article
        soup = BeautifulSoup(html, "html.parser")

        # remove nav noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe", "noscript"]):
            tag.decompose()

        seen, result = set(), []

        for a in soup.find_all("a", href=True):
            href  = a.get("href", "").strip()
            title = a.get_text(strip=True)

            if not href:
                continue

            # make absolute
            if href.startswith("/"):
                href = self._base_url + href
            elif not href.startswith("http"):
                continue

            # skip non-article patterns
            if any(s in href for s in SKIP_PATTERNS):
                continue

            # must be same domain
            if self._base_url.replace("https://","").replace("http://","") not in href:
                continue

            if not title or len(title) < 25:
                continue

            if href in seen:
                continue

            # bonus: prefer links that look like articles
            is_article = any(p in href for p in ARTICLE_PATTERNS) or len(href.split("/")) >= 5

            seen.add(href)
            result.append((is_article, title, href))

            if len(result) >= 60:
                break

        # sort — article-pattern links first
        result.sort(key=lambda x: not x[0])
        final = []
        for _, title, href in result[:25]:
            final.append(Article(
                title=title,
                url=href,
                published_date=datetime.now(timezone.utc),
                source_name=self.config.name,
                fetched_via="browser",
            ))

        log.info("[" + self.config.name + "]  " + str(len(final)) + " links extracted from page")
        return final