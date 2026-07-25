"""Fair Pay engine — deterministic band computation + one LLM call that
positions the candidate inside the computed band and writes the reasoning.

Pipeline: resolve role → compute band (MY anchors / SG Adzuna) → blend the
university fresh-grad band (decays over ~3 yrs) → trajectory + alternates →
LLM positioning → rule-based confidence. The server owns every number."""

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Optional

from ..llm import get_llm
from ..logging_config import logger
from ..prompts import FAIRPAY_SYSTEM
from ..schemas import (
    AlternateRoleOut,
    FairPayBand,
    FairPayConfidence,
    FairPayIn,
    FairPayOut,
    FairPayReasoning,
    ReceiptRow,
    TrajectoryPoint,
    UniContext,
)
from .fairpay_math import (
    Band,
    band_from_anchors,
    blend_bands,
    confidence_for,
    experience_position,
    growth_factor,
    university_weight,
)
from .fairpay_roles import find_role, match_role
from .salary import fetch_market_grounding

_DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "employability_dataset.json"
_dataset_cache: Optional[dict] = None

TRAJECTORY_OFFSETS = [0, 1, 3, 5]
MAX_ALTERNATES = 5


def _dataset() -> dict:
    global _dataset_cache
    if _dataset_cache is None:
        with open(_DATASET_PATH, encoding="utf-8") as f:
            _dataset_cache = json.load(f)
    return _dataset_cache


def _source_labels(ds: dict, ids: list[str]) -> list[str]:
    by_id = {s["id"]: s["label"] for s in ds.get("sources", [])}
    return [by_id[i] for i in ids if i in by_id]


def _resolve_university(ds: dict, university_id: Optional[str], degree_field: Optional[str]) -> Optional[dict]:
    if not university_id:
        return None
    for u in ds.get("universities", []):
        if u.get("id") != university_id:
            continue
        if degree_field:
            for d in u.get("degrees", []):
                if d.get("field") == degree_field:
                    return {"uni": u.get("name"), "field": d.get("field"),
                            "band": d.get("salary"), "rate": d.get("employment_rate_pct"),
                            "country": u.get("country"),
                            "source_ids": d.get("source_ids") or u.get("source_ids") or []}
        return {"uni": u.get("name"), "field": None, "band": None,
                "rate": u.get("employment_rate_pct"), "country": u.get("country"),
                "source_ids": u.get("source_ids") or []}
    return None


def _degree_band(uni: Optional[dict]) -> Optional[Band]:
    """Dataset degree band (p50 may be null) → math Band, monthly."""
    if not uni or not uni.get("band"):
        return None
    b = uni["band"]
    if b.get("p25") is None or b.get("p75") is None:
        return None
    p50 = b.get("p50") if b.get("p50") is not None else (b["p25"] + b["p75"]) / 2.0
    return Band(p25=float(b["p25"]), p50=float(p50), p75=float(b["p75"]),
                currency=b.get("currency", "SGD"), period="month")


def _monthly(g: dict) -> Band:
    """Adzuna grounding (annual) → monthly Band."""
    return Band(p25=g["p25"] / 12.0, p50=g["p50"] / 12.0, p75=g["p75"] / 12.0,
                currency=g["currency"], period="month")


def _usable_grounding(g: Optional[dict]) -> bool:
    """Adzuna sometimes returns all-zero percentiles (bucket floors missing);
    a band anchored at zero is worse than no band."""
    return bool(g) and g["p25"] > 0 and g["p50"] > 0 and g["p75"] > 0


async def _llm_reason(system: str, human: str) -> FairPayReasoning:
    """Isolated so tests can monkeypatch the LLM out."""
    llm = get_llm().with_structured_output(FairPayReasoning)
    return await llm.ainvoke([("system", system), ("human", human)])


def _fmt_band(b: Band) -> str:
    return f"{b['currency']} {b['p25']:,.0f}–{b['p75']:,.0f}/mo (median {b['p50']:,.0f})"


async def estimate_fair_pay(resume: dict, body: FairPayIn) -> FairPayOut:
    ds = _dataset()
    profile = resume.get("profile") or {}
    country = (body.country or "").upper()
    years = body.years if body.years is not None else float(profile.get("years_of_experience") or 0.0)

    roles = ds.get("roles", [])
    archetypes = profile.get("target_archetypes") or []
    role = find_role(roles, body.role_id) or match_role(
        roles, profile.get("headline"), *(archetypes[:2])
    )
    role_title = role["title"] if role else (profile.get("headline") or "Professional")

    # ── deterministic band ────────────────────────────────────────────────
    grounding_mode = "llm"
    adzuna_n: Optional[int] = None
    adzuna_attempted = role is not None and country == "SG"
    role_band: Optional[Band] = None
    my_anchors: Optional[dict] = None
    sources: list[str] = []

    if role and country == "MY" and role.get("salary", {}).get("MY"):
        my_anchors = role["salary"]["MY"]
        role_band = band_from_anchors(my_anchors, years)
        if role_band:
            grounding_mode = "data"
            sources = _source_labels(ds, my_anchors.get("source_ids", []))
    elif role and country == "SG":
        g = await fetch_market_grounding(role["title"], body.city_refine, country="sg")
        if _usable_grounding(g):
            role_band = _monthly(g)
            adzuna_n = g["sample_size"]
            grounding_mode = "data"
            sources = [f"Adzuna (SG, n={adzuna_n})"]
        elif g:
            logger.warning(
                f"Adzuna SG grounding unusable (zero percentiles, n={g['sample_size']})"
            )
        # trajectory shape can still borrow the role's MY anchors if present
        my_anchors = role.get("salary", {}).get("MY")

    uni = _resolve_university(ds, body.university_id, body.degree_field)
    w = university_weight(years)
    deg_band = _degree_band(uni)
    usable_deg = (
        deg_band is not None and w > 0
        and uni is not None and uni.get("country") == country
        and (role_band is None or deg_band["currency"] == role_band["currency"])
    )
    band = blend_bands(deg_band if usable_deg else None, role_band, w)
    used_degree_band = usable_deg

    ges_labels: list[str] = []
    if usable_deg and uni:
        ges_labels = _source_labels(ds, uni.get("source_ids", []))
        if not ges_labels:
            ges_labels = [f"{uni['uni']} graduate survey"]

    if band is not None and grounding_mode == "llm" and used_degree_band:
        grounding_mode = "data"  # degree-band-only grounding (e.g. Adzuna down)
        sources = sources or ges_labels
    if used_degree_band:
        for lbl in ges_labels:
            if lbl not in sources:
                sources.append(lbl)

    # ── LLM positioning + prose ───────────────────────────────────────────
    alternates_menu = "\n".join(
        f"- {r['id']}: {r['title']}" for r in roles
    )
    if band is not None:
        band_text = (
            f"## COMPUTED BAND (do not alter)\nRole: {role_title} · Country: {country} · "
            f"Experience: {years:.1f} yrs\nBand: {_fmt_band(band)}\n"
            f"University factor weight: {w:.2f}"
            + (f" ({uni['uni']}, {uni.get('field') or 'no per-degree data'})" if uni else " (no university selected)")
        )
    else:
        band_text = (
            f"## NO DATA BAND EXISTS\nTarget country: {country} · Role: {role_title} · "
            f"Experience: {years:.1f} yrs\nYou MUST supply llm_band (monthly"
            + (f", preferred currency {body.currency}" if body.currency else "")
            + ") and est_p50 on each alternate."
        )
    human = (
        f"{band_text}\n\n## ROLE MENU (pick alternates from these ids)\n{alternates_menu}"
        f"\n\n## Candidate resume\n\n{resume['markdown']}"
    )
    r = await _llm_reason(FAIRPAY_SYSTEM, human)

    if band is None:
        if not r.llm_band:
            raise ValueError("LLM-only mode requires llm_band")
        band = Band(p25=r.llm_band.p25, p50=r.llm_band.p50, p75=r.llm_band.p75,
                    currency=r.llm_band.currency, period="month")
        sources = ["LLM estimate"]

    position = max(0.0, min(1.0, r.position))
    point = band["p25"] + position * (band["p75"] - band["p25"])
    percentile = 25.0 + position * 50.0

    # ── trajectory ────────────────────────────────────────────────────────
    annotations = (r.milestone_annotations + [None] * 4)[:4]
    trajectory = []
    for i, off in enumerate(TRAJECTORY_OFFSETS):
        f = growth_factor(my_anchors, years, off)
        fb = _scale(band, f)
        trajectory.append(TrajectoryPoint(
            offset_years=off,
            point=point * f,
            band=FairPayBand(**fb),
            annotation=annotations[i],
        ))

    # ── alternates ────────────────────────────────────────────────────────
    alternates = await _build_alternates(ds, roles, r, country, years, point, band["currency"])

    receipt = _build_receipt(r, band, role_title, country, years, w, uni, sources, grounding_mode, used_degree_band)
    conf = confidence_for(grounding_mode, country, adzuna_n, used_degree_band)
    if grounding_mode == "llm" and adzuna_attempted:
        conf = {**conf, "reason": "ADZUNA_UNAVAILABLE"}

    out = FairPayOut(
        grounding_mode=grounding_mode,
        role_id=role["id"] if role else None,
        role_title=role_title,
        country=country,
        years=years,
        point=point,
        percentile=percentile,
        band=FairPayBand(**band),
        confidence=FairPayConfidence(**conf),
        receipt=receipt,
        trajectory=trajectory,
        alternates=alternates,
        leverage=r.leverage,
        summary=r.summary,
        uni_context=UniContext(name=uni["uni"], rate=uni.get("rate"), field=uni.get("field")) if uni else None,
        sources=sources,
        as_of=date.today().isoformat(),
    )
    logger.info(
        f"💰 FairPay: {out.band.currency} {out.point:,.0f}/mo P{out.percentile:.0f} "
        f"({out.confidence.level}/{out.confidence.reason}, mode={out.grounding_mode})"
    )
    return out


def _scale(b: Band, f: float) -> Band:
    return Band(p25=b["p25"] * f, p50=b["p50"] * f, p75=b["p75"] * f,
                currency=b["currency"], period=b["period"])


async def _build_alternates(
    ds: dict, roles: list[dict], r: FairPayReasoning,
    country: str, years: float, point: float, currency: str,
) -> list[AlternateRoleOut]:
    out: list[AlternateRoleOut] = []
    picks = [a for a in r.alternates if find_role(roles, a.role_id)][:MAX_ALTERNATES]

    async def band_for(role: dict) -> Optional[Band]:
        if country == "MY" and role.get("salary", {}).get("MY"):
            return band_from_anchors(role["salary"]["MY"], years)
        if country == "SG":
            g = await fetch_market_grounding(role["title"], country="sg")
            return _monthly(g) if _usable_grounding(g) else None
        return None

    computed = await asyncio.gather(*(band_for(find_role(roles, a.role_id)) for a in picks))
    for a, b in zip(picks, computed):
        if b is None and a.est_p50:
            b = Band(p25=a.est_p50 * 0.85, p50=a.est_p50, p75=a.est_p50 * 1.15,
                     currency=currency, period="month")
        if b is None:
            continue
        role = find_role(roles, a.role_id)
        delta = ((b["p50"] - point) / point * 100.0) if point > 0 else 0.0
        out.append(AlternateRoleOut(
            role_id=a.role_id, title=role["title"],
            band=FairPayBand(**b), delta_pct=round(delta, 1), note=a.note,
        ))
    return out


def _build_receipt(
    r: FairPayReasoning, band: Band, role_title: str, country: str,
    years: float, w: float, uni: Optional[dict], sources: list[str], mode: str,
    used_degree_band: bool = False,
) -> list[ReceiptRow]:
    t = experience_position(years)
    rows = [
        ReceiptRow(
            id="base_band", label="BASE_BAND",
            effect=f"{band['currency']} {band['p25']:,.0f}–{band['p75']:,.0f}",
            reasoning=r.base_band_reasoning,
            source=("LLM_ESTIMATE // NO_LOCAL_DATA" if mode == "llm" else " + ".join(sources) or None),
        ),
        ReceiptRow(
            id="experience", label="EXPERIENCE",
            effect=f"→ {t * 100:.0f}% of anchor range",
            reasoning=r.experience_reasoning,
        ),
    ]
    if uni:
        effect = f"×{w:.1f} influence" if used_degree_band else "context only"
        rows.append(ReceiptRow(id="university", label="UNIVERSITY",
                               effect=effect, reasoning=r.university_reasoning))
    delta = ((band["p25"] + max(0.0, min(1.0, r.position)) * (band["p75"] - band["p25"])) - band["p50"]) / band["p50"] * 100.0
    rows.append(ReceiptRow(id="resume", label="RESUME",
                           effect=f"{delta:+.0f}% vs median", reasoning=r.resume_reasoning))
    return rows
