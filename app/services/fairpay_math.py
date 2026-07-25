"""Deterministic band math for the Fair Pay engine.

Pure functions, no I/O, no LLM. Every number the /worth page shows is
computed here (or in the Adzuna percentile code) — the LLM only positions
the candidate inside these bands and writes prose.
"""

from typing import Optional, TypedDict


class Band(TypedDict):
    p25: float
    p50: float
    p75: float
    currency: str
    period: str  # always "month" in this module


#: Years of experience at which the senior anchor is fully reached.
CAP_YEARS = 10.0
#: Years over which a university's fresh-grad band fades to zero influence.
UNI_FADE_YEARS = 3.0
#: Generic compounding growth used for trajectories with no career anchors.
GENERIC_ANNUAL_GROWTH = 0.05
#: Relative half-width used when a role has anchors but no typical range.
DEFAULT_HALF_WIDTH = 0.15


def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def experience_position(years: float, cap_years: float = CAP_YEARS) -> float:
    """0 → junior anchor, 1 → senior anchor. Smooth and capped."""
    if cap_years <= 0:
        return 1.0
    return smoothstep(max(0.0, years) / cap_years)


def band_from_anchors(role_band: dict, years: float) -> Optional[Band]:
    """A P25/P50/P75 band at the given experience, from a dataset
    `roles[].salary["MY"]`-shaped dict (junior/senior anchors + typical range)."""
    typical = role_band.get("typical") or {}
    lo, hi = typical.get("lo"), typical.get("hi")
    junior, senior = role_band.get("junior"), role_band.get("senior")
    currency = role_band.get("currency", "MYR")
    period = role_band.get("period", "month")

    if junior is not None and senior is not None:
        anchor = junior + experience_position(years) * (senior - junior)
        if lo and hi and (lo + hi) > 0:
            r = (hi - lo) / (hi + lo)
        else:
            r = DEFAULT_HALF_WIDTH
        return Band(p25=anchor * (1 - r), p50=float(anchor), p75=anchor * (1 + r),
                    currency=currency, period=period)
    if lo is not None and hi is not None:
        return Band(p25=float(lo), p50=(lo + hi) / 2.0, p75=float(hi),
                    currency=currency, period=period)
    return None


def university_weight(years: float, fade_years: float = UNI_FADE_YEARS) -> float:
    return max(0.0, min(1.0, 1.0 - max(0.0, years) / fade_years))


def blend_bands(degree_band: Optional[Band], role_band: Optional[Band], w: float) -> Optional[Band]:
    """Elementwise blend of a fresh-grad degree band into a role band.
    The degree band stands alone when no role band exists; mismatched
    currencies never blend."""
    if degree_band is None or w <= 0:
        return role_band
    if role_band is None:
        return degree_band
    if degree_band["currency"] != role_band["currency"]:
        return role_band

    def mix(a: float, b: float) -> float:
        return w * a + (1.0 - w) * b

    return Band(
        p25=mix(degree_band["p25"], role_band["p25"]),
        p50=mix(degree_band["p50"], role_band["p50"]),
        p75=mix(degree_band["p75"], role_band["p75"]),
        currency=role_band["currency"],
        period=role_band["period"],
    )


def growth_factor(anchors: Optional[dict], years: float, offset: float) -> float:
    """Multiplier from `years` to `years + offset` along the junior→senior
    curve; generic compounding when no anchors exist."""
    if anchors and anchors.get("junior") is not None and anchors.get("senior") is not None:
        j, s = anchors["junior"], anchors["senior"]
        base = j + experience_position(years) * (s - j)
        future = j + experience_position(years + offset) * (s - j)
        return future / base if base > 0 else 1.0
    return (1.0 + GENERIC_ANNUAL_GROWTH) ** offset


def confidence_for(
    grounding_mode: str, country: str, adzuna_n: Optional[int], used_degree_band: bool
) -> dict:
    """Rule-based confidence — the LLM never grades its own homework."""
    if grounding_mode != "data":
        return {"level": "low", "reason": "LLM_ONLY"}
    if country == "MY":
        return {"level": "high", "reason": "JOBSTREET+HAYS_BAND"}
    if adzuna_n is not None:
        if adzuna_n >= 30:
            return {"level": "high", "reason": f"ADZUNA_N={adzuna_n}"}
        if adzuna_n >= 8:
            return {"level": "medium", "reason": f"ADZUNA_N={adzuna_n}"}
        return {"level": "low", "reason": f"ADZUNA_N={adzuna_n}"}
    if used_degree_band:
        return {"level": "medium", "reason": "GES_2025_DEGREE_BAND"}
    return {"level": "low", "reason": "LLM_ONLY"}
