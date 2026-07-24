"""Fetch a job description from a URL and reduce it to readable text.

Note: the CLI mandates Playwright for liveness verification because many job
pages are JS-rendered. Plain HTTP covers Greenhouse/Lever/Ashby-hosted pages
(server-rendered); for JS-heavy pages the caller gets a clear error and the
frontend should ask the user to paste the JD text instead.
"""

import httpx
from bs4 import BeautifulSoup

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


async def fetch_jd_text(url: str) -> str:
    if not url.startswith("https://"):
        raise JDFetchError("Only https:// URLs are allowed")
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers=_HEADERS
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (403, 401):
            raise JDFetchError(
                "Access blocked (403 Forbidden) by the target job portal — "
                "this company page blocks automated scraping. Please paste the job description text directly."
            ) from e
        raise JDFetchError(f"Could not fetch URL: {e}") from e
    except httpx.HTTPError as e:
        raise JDFetchError(f"Could not fetch URL: {e}") from e

    soup = BeautifulSoup(resp.text, "html.parser")
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

