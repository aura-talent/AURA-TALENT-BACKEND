"""Fetch a job description from a URL and reduce it to readable text.

Note: the CLI mandates Playwright for liveness verification because many job
pages are JS-rendered. Plain HTTP covers Greenhouse/Lever/Ashby-hosted pages
(server-rendered); for JS-heavy pages the caller gets a clear error and the
frontend should ask the user to paste the JD text instead.
"""

import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote

from ..config import settings
from ..logging_config import logger

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
MIN_JD_CHARS = 400


class JDFetchError(Exception):
    pass


async def _fetch_html(url: str, proxy_url: str | None = None) -> str:
    async with httpx.AsyncClient(
        timeout=25, follow_redirects=True, headers=_HEADERS, proxy=proxy_url
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


async def fetch_jd_text(url: str) -> str:
    if not url.startswith("https://"):
        raise JDFetchError("Only https:// URLs are allowed")

    html: str | None = None

    # Step 1: Direct fetch (fast & free)
    try:
        html = await _fetch_html(url)
    except httpx.HTTPStatusError as e:
        if e.response.status_code not in (403, 401, 429):
            raise JDFetchError(f"Could not fetch URL: {e}") from e
        logger.warning(
            f"⚠️  Direct fetch returned {e.response.status_code} for {url} — attempting proxy fallback..."
        )
    except httpx.HTTPError as e:
        logger.warning(
            f"⚠️  Direct fetch failed ({e}) for {url} — attempting proxy fallback..."
        )

    # Step 2: Proxy Fallback if direct fetch was blocked (e.g. 403 Forbidden)
    if html is None:
        if settings.scraper_api_key:
            # ScraperAPI integration (1,000 free requests/month)
            proxy_endpoint = (
                f"http://api.scraperapi.com?api_key={settings.scraper_api_key}&url={quote(url)}"
            )
            try:
                html = await _fetch_html(proxy_endpoint)
                logger.info(f"✅ Successfully fetched {url} via ScraperAPI proxy")
            except Exception as e:
                logger.error(f"❌ ScraperAPI proxy fetch failed: {e}")
        elif settings.scraper_proxy_url:
            # Custom proxy integration
            try:
                html = await _fetch_html(url, proxy_url=settings.scraper_proxy_url)
                logger.info(f"✅ Successfully fetched {url} via custom proxy")
            except Exception as e:
                logger.error(f"❌ Custom proxy fetch failed: {e}")

    # Step 3: If still no HTML, raise candidate-friendly 403 error
    if html is None:
        raise JDFetchError(
            "Access blocked (403 Forbidden) by the target job portal — "
            "this company page blocks automated cloud scrapers. Please paste the job description text directly."
        )

    # Step 4: Parse HTML into clean text
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = "\n".join(
        line.strip() for line in soup.get_text("\n").splitlines() if line.strip()
    )
    if len(text) < MIN_JD_CHARS:
        raise JDFetchError(
            "Page returned too little text — likely JS-rendered or the posting "
            "is closed. Paste the job description text directly instead."
        )
    return text[:30000]


