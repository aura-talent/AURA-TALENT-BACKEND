"""Work-animal trait engine — pure functions only, no I/O, no LLM.

The six bipolar axes (each in [-1, +1], canonical order everywhere):
  social       heads-down (-1)        -> people-facing (+1)
  motion       building/craft (-1)    -> persuasion/influence (+1)
  visibility   behind-the-scenes (-1) -> spotlight (+1)
  environment  structured/stable (-1) -> ambiguous/risky (+1)
  autonomy     solo (-1)              -> team-embedded (+1)
  north_star   mission/impact (-1)    -> comp/prestige (+1)
"""

import hashlib
import json
import math
import statistics
from pathlib import Path

AXES = ["social", "motion", "visibility", "environment", "autonomy", "north_star"]

_LR_RIGHT = 0.25   # right swipe: move a quarter of the way toward the job's traits
_LR_LEFT = 0.12    # left swipe: push directly away from the job's traits, gentler


def zero_vector() -> dict[str, float]:
    return dict.fromkeys(AXES, 0.0)


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def update_vector(
    vector: dict[str, float], traits: dict[str, float], direction: str
) -> dict[str, float]:
    """One swipe's effect on the user's revealed trait vector. Returns a new
    dict; never mutates the input."""
    if direction not in ("right", "left"):
        raise ValueError(f"direction must be 'right' or 'left', got {direction!r}")
    out = {}
    for axis in AXES:
        v = vector.get(axis, 0.0)
        t = traits.get(axis, 0.0)
        if direction == "right":
            out[axis] = _clamp(v + _LR_RIGHT * (t - v))
        else:
            out[axis] = _clamp(v - _LR_LEFT * t)
    return out


# Prototype vectors — each animal owns a region of trait space. Order of dict
# insertion is the deterministic tie-break. Chameleon has no region; it is the
# low-fixation special case in classify().
PROTOTYPES: dict[str, dict[str, float]] = {
    "owl":      dict(zip(AXES, [-0.8, -0.7, -0.8, -0.2, -0.5, -0.2])),
    "beaver":   dict(zip(AXES, [-0.6, -0.9, -0.5, -0.7,  0.3, -0.1])),
    "fox":      dict(zip(AXES, [ 0.0, -0.3,  0.0,  0.8,  0.0,  0.0])),
    "octopus":  dict(zip(AXES, [-0.3, -0.4, -0.2,  0.5, -0.8,  0.0])),
    "wolf":     dict(zip(AXES, [ 0.4,  0.2,  0.4,  0.1,  0.8,  0.7])),
    "hawk":     dict(zip(AXES, [ 0.5,  0.4,  0.9,  0.3,  0.3,  0.5])),
    "shark":    dict(zip(AXES, [ 0.6,  0.8,  0.5,  0.7,  0.0,  0.9])),
    "lion":     dict(zip(AXES, [ 0.9,  0.9,  0.9,  0.2,  0.5,  0.4])),
    "dolphin":  dict(zip(AXES, [ 0.9,  0.3,  0.2, -0.2,  0.9, -0.3])),
    "deer":     dict(zip(AXES, [ 0.2, -0.2, -0.3, -0.3,  0.4, -0.9])),
    "tortoise": dict(zip(AXES, [-0.4, -0.4, -0.4, -0.9,  0.2, -0.4])),
    "chameleon": dict.fromkeys(AXES, 0.0),
}

_CHAMELEON_FLATNESS = 0.22
_CHAMELEON_MIN_SWIPES = 10


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(a[k] * b[k] for k in AXES)
    na = math.sqrt(sum(a[k] ** 2 for k in AXES))
    nb = math.sqrt(sum(b[k] ** 2 for k in AXES))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def classify(vector: dict[str, float], swipe_count: int) -> tuple[str, float]:
    """Deterministic nearest-prototype mapping. Animals are lateral — the
    return value is a niche, never a rank. Confidence is cosine similarity
    remapped to [0, 1]."""
    flatness = sum(abs(vector.get(k, 0.0)) for k in AXES) / len(AXES)
    if flatness < _CHAMELEON_FLATNESS and swipe_count >= _CHAMELEON_MIN_SWIPES:
        return "chameleon", 0.6

    best_name, best_sim = "owl", -2.0
    for name, proto in PROTOTYPES.items():
        if name == "chameleon":
            continue
        sim = _cosine(vector, proto)
        if sim > best_sim:
            best_name, best_sim = name, sim
    return best_name, round((best_sim + 1) / 2, 4)


_SELECTIVE_MAX_RIGHT_RATE = 0.25
_ANALYTICAL_MIN_MS = 5000
_ANALYTICAL_MIN_CHANGES = 1.0
_EXPLORATORY_MIN_RIGHT_RATE = 0.6


def temperament(swipes: list[dict]) -> str:
    """Swipe *manner* → temperament modifier. Precedence is deliberate and
    deterministic: selective > analytical > exploratory > decisive."""
    if not swipes:
        return "decisive"
    right_rate = sum(1 for s in swipes if s["direction"] == "right") / len(swipes)
    median_ms = statistics.median(s["decision_ms"] for s in swipes)
    avg_changes = sum(s.get("direction_changes", 0) for s in swipes) / len(swipes)

    if right_rate <= _SELECTIVE_MAX_RIGHT_RATE:
        return "selective"
    if median_ms >= _ANALYTICAL_MIN_MS or avg_changes >= _ANALYTICAL_MIN_CHANGES:
        return "analytical"
    if right_rate >= _EXPLORATORY_MIN_RIGHT_RATE:
        return "exploratory"
    return "decisive"


def alignment(revealed: dict[str, float], stated: dict[str, float] | None) -> int | None:
    """Distance between revealed (swiped) and stated (onboarding) vectors,
    as 0-100. Self-referential by construction: it only ever compares the
    user to their own stated goals."""
    if stated is None:
        return None
    return round(50 * (1 + _cosine(revealed, stated)))


_SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "animal_seed_deck.json"


def card_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def load_seed_deck() -> list[dict]:
    with open(_SEED_PATH, encoding="utf-8") as f:
        cards = json.load(f)
    for c in cards:
        c["id"] = card_id(c["url"])
    return cards


def build_deck(
    jobs: list[dict], tagged_traits: list[dict[str, float]], count: int = 15
) -> list[dict]:
    """Zip scanned jobs with LLM-tagged traits into swipe cards; top up from
    the pre-tagged seed deck when the live feed is thin (cold start)."""
    deck = []
    for job, traits in list(zip(jobs, tagged_traits))[:count]:
        deck.append({
            "id": card_id(job["url"]),
            "company": job["company"],
            "title": job["title"],
            "url": job["url"],
            "location": job.get("location", ""),
            "source": job.get("source", ""),
            "traits": traits,
        })
    if len(deck) < count:
        have = {c["id"] for c in deck}
        for seed in load_seed_deck():
            if len(deck) >= count:
                break
            if seed["id"] not in have:
                deck.append(seed)
    return deck
