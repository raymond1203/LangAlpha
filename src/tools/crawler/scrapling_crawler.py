"""
Crawler backend using Scrapling library.

Implements a three-tier fetching strategy:
  Tier 1 (Fast):    AsyncFetcher.get() -- HTTP-only, TLS impersonation
  Tier 2 (Dynamic): DynamicFetcher.async_fetch() -- Playwright browser
  Tier 3 (Stealth): StealthyFetcher.async_fetch() -- anti-bot bypass

Automatic fallback: Tier 1 -> Tier 2 -> Tier 3
"""

import logging

import html2text

from .backend import CrawlOutput

logger = logging.getLogger(__name__)

# Signals that indicate Tier 1 content is blocked/empty and needs browser rendering
_BLOCKED_SIGNALS = [
    "cloudflare",
    "just a moment",
    "checking your browser",
    "enable javascript",
    "please enable js",
    "ray id",
    "access denied",
    "403 forbidden",
    "captcha",
]


def _needs_browser(html_body: str, status: int) -> bool:
    """Detect if HTTP-only fetch returned blocked/empty content."""
    if status >= 400:
        return True
    if not html_body or len(html_body.strip()) < 200:
        return True
    lower = html_body.lower()
    return any(signal in lower for signal in _BLOCKED_SIGNALS)


def _needs_stealth(html_body: str, status: int) -> bool:
    """Detect if dynamic fetch hit anti-bot protection."""
    if status in (401, 403):
        return True
    lower = (html_body or "").lower()
    # Cloudflare challenge
    if "cloudflare" in lower and ("ray id" in lower or "just a moment" in lower):
        return True
    # DataDome / generic anti-bot challenge (short page with JS challenge)
    if len(lower) < 2000 and ("enable js" in lower or "enable javascript" in lower):
        return True
    return False


def _html_to_markdown(html: str) -> str:
    """Convert HTML to clean markdown using html2text."""
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = False
    converter.body_width = 0  # No wrapping
    converter.ignore_emphasis = False
    return converter.handle(html)


def _extract_title(page) -> str:
    """Extract page title from Scrapling response."""
    try:
        title_el = page.css("title::text")
        return title_el.get() or ""
    except Exception:
        return ""


class ScraplingCrawler:
    """
    Async crawler using Scrapling with tiered fetching.

    Satisfies the CrawlerBackend protocol.
    """

    def __init__(
        self,
        timeout: int = 30000,
        disable_resources: bool = True,
        network_idle: bool = True,
    ):
        self.timeout = timeout
        self.disable_resources = disable_resources
        self.network_idle = network_idle

    async def crawl(self, url: str) -> str:
        """Crawl and return markdown."""
        output = await self.crawl_with_metadata(url)
        return output.markdown

    async def crawl_with_metadata(self, url: str) -> CrawlOutput:
        """Crawl with tiered fallback, return CrawlOutput."""
        from .extractors.base import _validate_url
        _validate_url(url)

        # --- Tier 1: Fast HTTP fetch (requires curl_cffi) ---
        try:
            page, html_body, status = await self._tier1_fetch(url)
            if not _needs_browser(html_body, status):
                title = _extract_title(page)
                markdown = _html_to_markdown(html_body)
                logger.debug(f"Tier 1 (fast) succeeded for {url}")
                return CrawlOutput(title=title, html=html_body, markdown=markdown)
            logger.debug(f"Tier 1 insufficient for {url}, escalating to Tier 2")
        except ImportError:
            # curl_cffi not installed — skip Tier 1 (scrapling without [fetchers])
            logger.debug(f"Tier 1 unavailable (curl_cffi not installed), using Tier 2 for {url}")
        except Exception as e:
            logger.debug(f"Tier 1 failed for {url}: {e}, escalating to Tier 2")

        # --- Tier 2: Dynamic browser fetch ---
        try:
            page, html_body, status = await self._tier2_fetch(url)
            if not _needs_stealth(html_body, status):
                title = _extract_title(page)
                markdown = _html_to_markdown(html_body)
                logger.debug(f"Tier 2 (dynamic) succeeded for {url}")
                return CrawlOutput(title=title, html=html_body, markdown=markdown)
            logger.debug(f"Tier 2 blocked for {url}, escalating to Tier 3")
        except Exception as e:
            logger.debug(f"Tier 2 failed for {url}: {e}, escalating to Tier 3")

        # --- Tier 3: Stealth fetch ---
        try:
            page, html_body, status = await self._tier3_fetch(url)
            if _needs_stealth(html_body, status):
                logger.debug(f"Tier 3 still blocked for {url} (status={status})")
                return CrawlOutput(title="", html="", markdown="")
            title = _extract_title(page)
            markdown = _html_to_markdown(html_body)
            logger.debug(f"Tier 3 (stealth) completed for {url} (status={status})")
            return CrawlOutput(title=title, html=html_body, markdown=markdown)
        except Exception as e:
            logger.debug(f"Tier 3 failed for {url}: {e}")
            return CrawlOutput(title="", html="", markdown="")

    async def _tier1_fetch(self, url: str):
        from scrapling.fetchers import AsyncFetcher

        page = await AsyncFetcher.get(
            url,
            stealthy_headers=True,
            follow_redirects=True,
            timeout=self.timeout / 1000,  # ms → seconds (curl_cffi convention)
        )
        html_body = page.body.decode(page.encoding or "utf-8", errors="replace")
        return page, html_body, page.status

    async def _tier2_fetch(self, url: str):
        from scrapling.fetchers import DynamicFetcher

        page = await DynamicFetcher.async_fetch(
            url,
            headless=True,
            disable_resources=self.disable_resources,
            network_idle=self.network_idle,
            timeout=self.timeout,
        )
        html_body = page.body.decode(page.encoding or "utf-8", errors="replace")
        return page, html_body, page.status

    async def _tier3_fetch(self, url: str):
        from scrapling.fetchers import StealthyFetcher

        page = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            solve_cloudflare=True,
            network_idle=self.network_idle,
            timeout=self.timeout,
        )
        html_body = page.body.decode(page.encoding or "utf-8", errors="replace")
        return page, html_body, page.status

    async def shutdown(self) -> None:
        """No persistent resources to clean up (Scrapling manages its own)."""
        pass
