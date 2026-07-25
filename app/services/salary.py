"""Market salary grounding via the Adzuna salary API.

Adzuna's `/jobs/{country}/histogram` returns a distribution of advertised
salaries for a search (job title + optional location). We turn that into
P25/P50/P75 base-salary bands and a sample count, which the LLM then uses as
an anchor when reasoning about the specific role and candidate.

Degrades gracefully: returns None when credentials are missing or the call
fails, so the salary node can fall back to an LLM-only (low-confidence)
estimate without breaking the evaluation.
"""

from typing import Optional, TypedDict

import httpx

from ..config import settings
from ..logging_config import logger

_BASE = "https://api.adzuna.com/v1/api"


class MarketGrounding(TypedDict):
    currency: str
    p25: float
    p50: float
    p75: float
    sample_size: int
    country: str


def _percentiles_from_histogram(hist: dict[str, int]) -> Optional[tuple[float, float, float, int]]:
    """Adzuna histogram is {salary_floor: count}. Reconstruct weighted
    percentiles from the bucketed counts."""
    buckets = sorted((float(k), int(v)) for k, v in hist.items() if v)
    total = sum(c for _, c in buckets)
    if total == 0 or not buckets:
        return None

    def at(p: float) -> float:
        target = p * total
        cum = 0
        for floor, count in buckets:
            cum += count
            if cum >= target:
                return floor
        return buckets[-1][0]

    return at(0.25), at(0.50), at(0.75), total


_CURRENCY_BY_COUNTRY = {
    "gb": "GBP", "us": "USD", "au": "AUD", "ca": "CAD", "de": "EUR",
    "fr": "EUR", "nl": "EUR", "at": "EUR", "in": "INR", "sg": "SGD",
    "nz": "NZD", "pl": "PLN", "za": "ZAR", "br": "BRL", "it": "EUR", "es": "EUR",
}


async def fetch_market_grounding(
    title: str, location: Optional[str] = None, country: Optional[str] = None
) -> Optional[MarketGrounding]:
    """Best-effort market band for a role. None when unavailable.
    `country` (lowercase Adzuna code) overrides the global setting —
    the Fair Pay engine passes the user's actual selection."""
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        return None

    country = (country or settings.adzuna_country or "us").lower()
    url = f"{_BASE}/jobs/{country}/histogram"
    params = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "what": title,
        "content-type": "application/json",
    }
    if location:
        params["where"] = location

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"Adzuna histogram fetch failed for '{title}': {e}")
        return None

    hist = data.get("histogram")
    if not isinstance(hist, dict):
        return None
    pct = _percentiles_from_histogram(hist)
    if not pct:
        return None

    p25, p50, p75, total = pct
    logger.info(
        f"💷 Adzuna grounding for '{title}' ({country}): "
        f"P25={p25:.0f} P50={p50:.0f} P75={p75:.0f} n={total}"
    )
    return MarketGrounding(
        currency=_CURRENCY_BY_COUNTRY.get(country, "USD"),
        p25=p25,
        p50=p50,
        p75=p75,
        sample_size=total,
        country=country,
    )
