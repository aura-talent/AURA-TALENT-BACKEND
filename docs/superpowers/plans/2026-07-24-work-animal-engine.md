# Work-Animal Engine (Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend trait engine + API for the work-animal module: job trait tagging, per-user evolving trait vector, deterministic 12-animal classifier, temperament, alignment meter, swipe storage, shortlist — per the approved spec at `AURA-TALENT-FRONTEND/docs/superpowers/specs/2026-07-24-work-animal-module-design.md`.

**Architecture:** Pure-function trait math and classifier in `app/services/animal.py` (no I/O), LLM calls isolated in `app/graphs/animal.py` (trait tagging, stated-goals tagging, explanation copy), Supabase persistence added to `app/storage.py`, one new router `app/routers/animal.py` under `/api/v1` behind the existing API-key gate.

**Tech Stack:** FastAPI, Pydantic v2, LangChain `get_llm().with_structured_output(...)`, Supabase (existing `storage.supabase` proxy), pytest with `monkeypatch` + `MagicMock` (existing patterns in `tests/test_career_map_storage.py`).

**Working directory:** `AURA-TALENT-BACKEND` (this repo). All paths below are relative to it. Run tests with `uv run pytest`.

## Global Constraints

- Animals are **lateral** — classifier returns a niche, never a ranking. No scoring of animals anywhere.
- Deterministic classification: vector → animal is pure math, no LLM. LLM writes only copy.
- Right-swipe = shortlist interest, never an application. No auto-apply paths.
- Alignment copy is self-referential ("drift from *your* stated goal") and must include a "play". Never "you got worse".
- Six trait axes, each in [-1, +1], in this exact order everywhere:
  `["social", "motion", "visibility", "environment", "autonomy", "north_star"]`
  (social: heads-down→people-facing; motion: building→persuasion; visibility: behind-the-scenes→spotlight; environment: structured→ambiguous; autonomy: solo→team-embedded; north_star: mission→comp/prestige)
- 12 animal ids, snake_case: `owl, beaver, fox, octopus, wolf, hawk, shark, lion, dolphin, deer, tortoise, chameleon`.
- 4 temperament ids: `decisive, analytical, exploratory, selective`.
- All new endpoints under the `/animal` prefix, registered in `app/main.py` with the existing `deps = [Depends(require_api_key)]`.
- Supabase tables `animal_states` and `animal_swipes` must be created in the Supabase console (see Task 5 notes) — `init_db()` is a no-op in this codebase.

---

### Task 1: Trait vector math (`app/services/animal.py`)

**Files:**
- Create: `app/services/animal.py`
- Test: `tests/test_animal_vector.py`

**Interfaces:**
- Produces: `AXES: list[str]` (the 6 axis names, canonical order); `zero_vector() -> dict[str, float]`; `update_vector(vector: dict[str, float], traits: dict[str, float], direction: str) -> dict[str, float]` (direction is `"right"` or `"left"`; returns a NEW dict, input not mutated; all values clamped to [-1, 1]).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_animal_vector.py
import pytest

from app.services import animal


def test_axes_canonical_order():
    assert animal.AXES == [
        "social", "motion", "visibility", "environment", "autonomy", "north_star"
    ]


def test_zero_vector():
    v = animal.zero_vector()
    assert set(v) == set(animal.AXES)
    assert all(x == 0.0 for x in v.values())


def test_right_swipe_pulls_toward_traits():
    v = animal.zero_vector()
    traits = dict.fromkeys(animal.AXES, 0.0) | {"social": 1.0}
    out = animal.update_vector(v, traits, "right")
    assert out["social"] == pytest.approx(0.25)   # lr_right * (1.0 - 0.0)
    assert out["motion"] == 0.0
    assert v["social"] == 0.0                      # input not mutated


def test_left_swipe_pushes_away():
    v = animal.zero_vector()
    traits = dict.fromkeys(animal.AXES, 0.0) | {"visibility": 1.0}
    out = animal.update_vector(v, traits, "left")
    assert out["visibility"] == pytest.approx(-0.12)  # -lr_left * trait


def test_values_clamped():
    v = dict.fromkeys(animal.AXES, 0.0) | {"social": 0.95}
    traits = dict.fromkeys(animal.AXES, 0.0) | {"social": 1.0}
    out = animal.update_vector(v, traits, "right")
    assert out["social"] <= 1.0
    v2 = dict.fromkeys(animal.AXES, 0.0) | {"social": -0.99}
    out2 = animal.update_vector(v2, traits, "left")
    assert out2["social"] >= -1.0


def test_bad_direction_raises():
    with pytest.raises(ValueError):
        animal.update_vector(animal.zero_vector(), animal.zero_vector(), "up")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_animal_vector.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError` or `AttributeError` (module `app.services.animal` does not exist).

- [ ] **Step 3: Write minimal implementation**

```python
# app/services/animal.py
"""Work-animal trait engine — pure functions only, no I/O, no LLM.

The six bipolar axes (each in [-1, +1], canonical order everywhere):
  social       heads-down (-1)        -> people-facing (+1)
  motion       building/craft (-1)    -> persuasion/influence (+1)
  visibility   behind-the-scenes (-1) -> spotlight (+1)
  environment  structured/stable (-1) -> ambiguous/risky (+1)
  autonomy     solo (-1)              -> team-embedded (+1)
  north_star   mission/impact (-1)    -> comp/prestige (+1)
"""

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_animal_vector.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/animal.py tests/test_animal_vector.py
git commit -m "feat(animal): trait axes and swipe vector math"
```

---

### Task 2: Deterministic 12-animal classifier

**Files:**
- Modify: `app/services/animal.py` (append)
- Test: `tests/test_animal_classifier.py`

**Interfaces:**
- Consumes: `AXES`, `zero_vector()` from Task 1.
- Produces: `PROTOTYPES: dict[str, dict[str, float]]` (12 animal ids → prototype vectors); `classify(vector: dict[str, float], swipe_count: int) -> tuple[str, float]` returning `(animal_id, confidence)` where confidence is cosine similarity in [0, 1] (chameleon returns fixed 0.6). Chameleon rule: mean absolute value of the vector < 0.22 **and** `swipe_count >= 10`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_animal_classifier.py
from app.services import animal


def _vec(**kw):
    return dict.fromkeys(animal.AXES, 0.0) | kw


def test_twelve_prototypes():
    assert set(animal.PROTOTYPES) == {
        "owl", "beaver", "fox", "octopus", "wolf", "hawk",
        "shark", "lion", "dolphin", "deer", "tortoise", "chameleon",
    }
    for proto in animal.PROTOTYPES.values():
        assert set(proto) == set(animal.AXES)


def test_heads_down_craft_is_owl():
    v = _vec(social=-0.8, motion=-0.7, visibility=-0.8, autonomy=-0.5)
    name, conf = animal.classify(v, swipe_count=15)
    assert name == "owl"
    assert 0.0 <= conf <= 1.0


def test_spotlight_persuasion_is_lion():
    v = _vec(social=0.9, motion=0.9, visibility=0.9, autonomy=0.5)
    name, _ = animal.classify(v, swipe_count=15)
    assert name == "lion"


def test_stability_seeker_is_tortoise():
    v = _vec(environment=-0.9, north_star=-0.4, social=-0.4, motion=-0.4, visibility=-0.4)
    name, _ = animal.classify(v, swipe_count=15)
    assert name == "tortoise"


def test_flat_vector_with_enough_swipes_is_chameleon():
    name, conf = animal.classify(animal.zero_vector(), swipe_count=12)
    assert name == "chameleon"
    assert conf == 0.6


def test_flat_vector_few_swipes_is_not_chameleon():
    # Too few swipes to call "low fixation" — fall through to nearest prototype.
    name, _ = animal.classify(animal.zero_vector(), swipe_count=3)
    assert name != "chameleon"


def test_deterministic():
    v = _vec(environment=0.8, motion=-0.3)
    assert animal.classify(v, 15) == animal.classify(v, 15)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_animal_classifier.py -v`
Expected: FAIL with `AttributeError: module 'app.services.animal' has no attribute 'PROTOTYPES'`.

- [ ] **Step 3: Write minimal implementation (append to `app/services/animal.py`)**

```python
import math

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_animal_classifier.py tests/test_animal_vector.py -v`
Expected: all passed (classifier tests + Task 1 regression).

- [ ] **Step 5: Commit**

```bash
git add app/services/animal.py tests/test_animal_classifier.py
git commit -m "feat(animal): deterministic 12-animal classifier"
```

---

### Task 3: Temperament + alignment

**Files:**
- Modify: `app/services/animal.py` (append)
- Test: `tests/test_animal_temperament.py`

**Interfaces:**
- Consumes: `AXES` from Task 1.
- Produces: `temperament(swipes: list[dict]) -> str` where each swipe dict has `direction: str`, `decision_ms: int`, `direction_changes: int`; `alignment(revealed: dict[str, float], stated: dict[str, float] | None) -> int | None` returning 0–100 or None when no stated goals exist.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_animal_temperament.py
from app.services import animal


def _swipes(n_right, n_left, ms=3000, changes=0):
    s = [{"direction": "right", "decision_ms": ms, "direction_changes": changes}] * n_right
    s += [{"direction": "left", "decision_ms": ms, "direction_changes": changes}] * n_left
    return s


def test_low_right_rate_is_selective():
    assert animal.temperament(_swipes(2, 10)) == "selective"


def test_slow_or_wavering_is_analytical():
    assert animal.temperament(_swipes(6, 6, ms=6000)) == "analytical"
    assert animal.temperament(_swipes(6, 6, ms=3000, changes=2)) == "analytical"


def test_high_right_rate_is_exploratory():
    assert animal.temperament(_swipes(10, 3, ms=2500)) == "exploratory"


def test_default_is_decisive():
    assert animal.temperament(_swipes(6, 7, ms=1500)) == "decisive"


def test_empty_swipes_is_decisive():
    assert animal.temperament([]) == "decisive"


def test_alignment_identical_is_100():
    v = dict.fromkeys(animal.AXES, 0.5)
    assert animal.alignment(v, v) == 100


def test_alignment_opposite_is_0():
    v = dict.fromkeys(animal.AXES, 0.5)
    w = dict.fromkeys(animal.AXES, -0.5)
    assert animal.alignment(v, w) == 0


def test_alignment_none_when_no_stated():
    assert animal.alignment(dict.fromkeys(animal.AXES, 0.5), None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_animal_temperament.py -v`
Expected: FAIL with `AttributeError` (`temperament` not defined).

- [ ] **Step 3: Write minimal implementation (append to `app/services/animal.py`)**

```python
import statistics

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_animal_temperament.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/animal.py tests/test_animal_temperament.py
git commit -m "feat(animal): temperament rules and alignment meter"
```

---

### Task 4: Seed deck data + deck builder

**Files:**
- Create: `app/data/animal_seed_deck.json`
- Modify: `app/services/animal.py` (append)
- Test: `tests/test_animal_deck.py`

**Interfaces:**
- Consumes: `AXES` from Task 1.
- Produces: `card_id(url: str) -> str` (sha1 hex, first 12 chars); `build_deck(jobs: list[dict], tagged_traits: list[dict[str, float]], count: int = 15) -> list[dict]` — zips scanned jobs (shape of `JobPosting`: `company, title, url, location, source`) with their trait dicts into card dicts, then tops up from the seed deck (which carries pre-computed traits, no LLM needed) when short. Card dict shape: `{"id", "company", "title", "url", "location", "source", "traits"}`. `load_seed_deck() -> list[dict]` returns the seed cards.

- [ ] **Step 1: Create the seed deck data file**

15 representative postings spanning the trait axes (real companies, canonical career URLs, traits hand-assigned). Create `app/data/animal_seed_deck.json`:

```json
[
  {"company": "Anthropic", "title": "Research Engineer, Interpretability", "url": "https://www.anthropic.com/careers/seed-interp", "location": "San Francisco", "source": "seed",
   "traits": {"social": -0.8, "motion": -0.8, "visibility": -0.6, "environment": 0.2, "autonomy": -0.3, "north_star": -0.5}},
  {"company": "Stripe", "title": "Backend Engineer, Payments Infrastructure", "url": "https://stripe.com/jobs/seed-payments", "location": "Remote", "source": "seed",
   "traits": {"social": -0.6, "motion": -0.9, "visibility": -0.5, "environment": -0.4, "autonomy": 0.2, "north_star": 0.3}},
  {"company": "YC Startup (Stealth)", "title": "Founding Engineer", "url": "https://www.workatastartup.com/seed-founding", "location": "San Francisco", "source": "seed",
   "traits": {"social": 0.1, "motion": -0.2, "visibility": 0.2, "environment": 0.95, "autonomy": -0.4, "north_star": 0.2}},
  {"company": "Google", "title": "Staff Software Engineer, Search", "url": "https://careers.google.com/seed-staff-search", "location": "Mountain View", "source": "seed",
   "traits": {"social": -0.2, "motion": -0.6, "visibility": 0.1, "environment": -0.7, "autonomy": 0.4, "north_star": 0.6}},
  {"company": "Salesforce", "title": "Enterprise Account Executive", "url": "https://careers.salesforce.com/seed-ae", "location": "New York", "source": "seed",
   "traits": {"social": 0.95, "motion": 0.95, "visibility": 0.6, "environment": 0.1, "autonomy": 0.3, "north_star": 0.8}},
  {"company": "Doctors Without Borders", "title": "Field Operations Coordinator", "url": "https://www.msf.org/seed-field-ops", "location": "Global", "source": "seed",
   "traits": {"social": 0.7, "motion": 0.1, "visibility": -0.1, "environment": 0.7, "autonomy": 0.6, "north_star": -0.95}},
  {"company": "Jane Street", "title": "Quantitative Trader", "url": "https://www.janestreet.com/seed-qt", "location": "New York", "source": "seed",
   "traits": {"social": 0.2, "motion": 0.4, "visibility": 0.0, "environment": 0.6, "autonomy": 0.1, "north_star": 0.95}},
  {"company": "GitLab", "title": "Senior Product Manager, Remote-first", "url": "https://about.gitlab.com/jobs/seed-pm", "location": "Remote", "source": "seed",
   "traits": {"social": 0.6, "motion": 0.3, "visibility": 0.3, "environment": 0.0, "autonomy": 0.7, "north_star": 0.1}},
  {"company": "Singapore GovTech", "title": "Software Engineer, Public Sector", "url": "https://www.tech.gov.sg/careers/seed-swe", "location": "Singapore", "source": "seed",
   "traits": {"social": 0.0, "motion": -0.5, "visibility": -0.4, "environment": -0.95, "autonomy": 0.4, "north_star": -0.6}},
  {"company": "Vercel", "title": "Developer Advocate", "url": "https://vercel.com/careers/seed-devrel", "location": "Remote", "source": "seed",
   "traits": {"social": 0.8, "motion": 0.5, "visibility": 0.95, "environment": 0.2, "autonomy": 0.0, "north_star": 0.0}},
  {"company": "Netflix", "title": "Engineering Manager, Streaming Platform", "url": "https://jobs.netflix.com/seed-em", "location": "Los Gatos", "source": "seed",
   "traits": {"social": 0.7, "motion": 0.4, "visibility": 0.5, "environment": 0.0, "autonomy": 0.8, "north_star": 0.5}},
  {"company": "Figma", "title": "Freelance Brand Illustrator (Contract)", "url": "https://www.figma.com/careers/seed-illustrator", "location": "Remote", "source": "seed",
   "traits": {"social": -0.4, "motion": -0.6, "visibility": 0.3, "environment": 0.5, "autonomy": -0.9, "north_star": -0.2}},
  {"company": "McKinsey & Company", "title": "Associate Consultant", "url": "https://www.mckinsey.com/careers/seed-associate", "location": "Multiple", "source": "seed",
   "traits": {"social": 0.8, "motion": 0.7, "visibility": 0.7, "environment": 0.3, "autonomy": 0.6, "north_star": 0.7}},
  {"company": "Wikimedia Foundation", "title": "Site Reliability Engineer", "url": "https://wikimediafoundation.org/seed-sre", "location": "Remote", "source": "seed",
   "traits": {"social": -0.7, "motion": -0.7, "visibility": -0.8, "environment": -0.2, "autonomy": 0.1, "north_star": -0.8}},
  {"company": "DBS Bank", "title": "Relationship Manager, Wealth", "url": "https://www.dbs.com/careers/seed-rm", "location": "Singapore", "source": "seed",
   "traits": {"social": 0.9, "motion": 0.8, "visibility": 0.4, "environment": -0.5, "autonomy": 0.3, "north_star": 0.6}}
]
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_animal_deck.py
from app.services import animal


def _job(i):
    return {"company": f"Co{i}", "title": f"Role {i}", "url": f"https://x.com/{i}",
            "location": "Remote", "source": "greenhouse"}


def _traits():
    return dict.fromkeys(animal.AXES, 0.1)


def test_card_id_stable_and_short():
    a = animal.card_id("https://x.com/1")
    assert a == animal.card_id("https://x.com/1")
    assert len(a) == 12
    assert a != animal.card_id("https://x.com/2")


def test_seed_deck_loads_15_tagged_cards():
    seed = animal.load_seed_deck()
    assert len(seed) == 15
    for card in seed:
        assert set(card["traits"]) == set(animal.AXES)
        assert card["id"] == animal.card_id(card["url"])
        assert card["source"] == "seed"


def test_build_deck_zips_jobs_with_traits():
    jobs = [_job(i) for i in range(15)]
    deck = animal.build_deck(jobs, [_traits()] * 15, count=15)
    assert len(deck) == 15
    assert deck[0]["company"] == "Co0"
    assert deck[0]["id"] == animal.card_id("https://x.com/0")
    assert deck[0]["traits"] == _traits()


def test_build_deck_tops_up_from_seed_when_short():
    jobs = [_job(i) for i in range(4)]
    deck = animal.build_deck(jobs, [_traits()] * 4, count=15)
    assert len(deck) == 15
    assert sum(1 for c in deck if c["source"] == "seed") == 11


def test_build_deck_empty_jobs_is_all_seed():
    deck = animal.build_deck([], [], count=15)
    assert len(deck) == 15
    assert all(c["source"] == "seed" for c in deck)


def test_build_deck_caps_at_count():
    jobs = [_job(i) for i in range(30)]
    deck = animal.build_deck(jobs, [_traits()] * 30, count=15)
    assert len(deck) == 15
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_animal_deck.py -v`
Expected: FAIL with `AttributeError` (`card_id` not defined).

- [ ] **Step 4: Write minimal implementation (append to `app/services/animal.py`)**

```python
import hashlib
import json
from pathlib import Path

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_animal_deck.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add app/data/animal_seed_deck.json app/services/animal.py tests/test_animal_deck.py
git commit -m "feat(animal): seed deck and deck builder with cold-start fallback"
```

---

### Task 5: Storage (Supabase persistence)

**Files:**
- Modify: `app/storage.py` (append at end)
- Test: `tests/test_animal_storage.py`

**Interfaces:**
- Produces: `get_animal_state(user_id: str) -> dict | None`; `save_animal_state(user_id: str, state: dict) -> None` (upsert on `user_id`); `append_animal_swipes(user_id: str, swipes: list[dict]) -> None`; `get_animal_shortlist(user_id: str) -> list[dict]` (card dicts of right-swipes, most recent first, deduped by card id).
- State dict shape (JSON round-tripped through the `state_json` column): `{"vector": dict, "animal": str, "confidence": float, "temperament": str, "alignment": int|None, "stated": dict|None, "swipe_count": int, "history": list[{"animal": str, "at": iso}], "copy": dict|None}`.

**Supabase console SQL (run manually — `init_db()` is a no-op in this repo).** Include this in the task PR description for whoever owns the Supabase project:

```sql
create table if not exists animal_states (
  user_id text primary key,
  state_json jsonb not null,
  updated_at timestamptz not null default now()
);
create table if not exists animal_swipes (
  id bigint generated always as identity primary key,
  user_id text not null,
  card_json jsonb not null,
  direction text not null check (direction in ('left','right')),
  decision_ms integer not null default 0,
  direction_changes integer not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists animal_swipes_user_idx on animal_swipes (user_id, created_at desc);
```

- [ ] **Step 1: Write the failing tests** (same `_wire` MagicMock pattern as `tests/test_career_map_storage.py`)

```python
# tests/test_animal_storage.py
import json
from unittest.mock import MagicMock

from app import storage


def _wire(mock_rows):
    client = MagicMock()
    table = MagicMock()
    client.table.return_value = table
    select = MagicMock()
    table.select.return_value = select
    eq = MagicMock()
    select.eq.return_value = eq
    eq.execute.return_value = MagicMock(data=mock_rows)
    # for shortlist: .eq().eq().order().execute()
    eq.eq.return_value = eq
    eq.order.return_value = eq
    return client, table


def test_get_animal_state_missing_returns_none(monkeypatch):
    client, _ = _wire([])
    monkeypatch.setattr(storage, "supabase", client)
    assert storage.get_animal_state("u1") is None


def test_get_animal_state_parses_json_string(monkeypatch):
    state = {"animal": "owl", "swipe_count": 15}
    client, _ = _wire([{"user_id": "u1", "state_json": json.dumps(state)}])
    monkeypatch.setattr(storage, "supabase", client)
    assert storage.get_animal_state("u1") == state


def test_save_animal_state_upserts(monkeypatch):
    client, table = _wire([])
    monkeypatch.setattr(storage, "supabase", client)
    storage.save_animal_state("u1", {"animal": "fox"})
    args = table.upsert.call_args[0][0]
    assert args["user_id"] == "u1"
    assert args["state_json"] == {"animal": "fox"}
    assert "updated_at" in args


def test_append_animal_swipes_inserts_rows(monkeypatch):
    client, table = _wire([])
    monkeypatch.setattr(storage, "supabase", client)
    storage.append_animal_swipes("u1", [
        {"card": {"id": "abc", "url": "https://x.com/1"}, "direction": "right",
         "decision_ms": 1200, "direction_changes": 0},
    ])
    rows = table.insert.call_args[0][0]
    assert rows[0]["user_id"] == "u1"
    assert rows[0]["direction"] == "right"
    assert rows[0]["card_json"] == {"id": "abc", "url": "https://x.com/1"}


def test_shortlist_returns_right_swipe_cards_deduped(monkeypatch):
    rows = [
        {"card_json": {"id": "a", "title": "Role A"}, "direction": "right"},
        {"card_json": json.dumps({"id": "b", "title": "Role B"}), "direction": "right"},
        {"card_json": {"id": "a", "title": "Role A"}, "direction": "right"},
    ]
    client, _ = _wire(rows)
    monkeypatch.setattr(storage, "supabase", client)
    out = storage.get_animal_shortlist("u1")
    assert [c["id"] for c in out] == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_animal_storage.py -v`
Expected: FAIL with `AttributeError: module 'app.storage' has no attribute 'get_animal_state'`.

- [ ] **Step 3: Write minimal implementation (append to `app/storage.py`)**

```python
# ── Work-animal module ─────────────────────────────────────────────


def get_animal_state(user_id: str) -> dict | None:
    res = supabase.table("animal_states").select("*").eq("user_id", user_id).execute()
    if not res.data:
        return None
    state = res.data[0]["state_json"]
    if isinstance(state, str):
        state = json.loads(state)
    return state


def save_animal_state(user_id: str, state: dict) -> None:
    supabase.table("animal_states").upsert({
        "user_id": user_id,
        "state_json": state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).execute()


def append_animal_swipes(user_id: str, swipes: list[dict]) -> None:
    rows = [{
        "user_id": user_id,
        "card_json": s["card"],
        "direction": s["direction"],
        "decision_ms": s.get("decision_ms", 0),
        "direction_changes": s.get("direction_changes", 0),
    } for s in swipes]
    if rows:
        supabase.table("animal_swipes").insert(rows).execute()


def get_animal_shortlist(user_id: str) -> list[dict]:
    res = (
        supabase.table("animal_swipes").select("card_json, direction")
        .eq("user_id", user_id).eq("direction", "right")
        .order("created_at", desc=True).execute()
    )
    out, seen = [], set()
    for row in res.data or []:
        card = row["card_json"]
        if isinstance(card, str):
            card = json.loads(card)
        if card["id"] not in seen:
            seen.add(card["id"])
            out.append(card)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_animal_storage.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/storage.py tests/test_animal_storage.py
git commit -m "feat(animal): supabase persistence for states, swipes, shortlist"
```

---

### Task 6: LLM tagging + explanation copy (`app/graphs/animal.py`)

**Files:**
- Modify: `app/prompts.py` (append two prompts)
- Modify: `app/schemas.py` (append structured-output models)
- Create: `app/graphs/animal.py`
- Test: `tests/test_animal_graph.py`

**Interfaces:**
- Consumes: `get_llm()` from `app/llm.py`; `AXES` from Task 1.
- Produces (all async): `tag_jobs(jobs: list[dict]) -> list[dict[str, float]]` (one trait dict per job, same order); `tag_stated(profile: dict) -> dict[str, float]` (stated-goals vector from the resume profile); `write_copy(animal_id: str, temperament: str, alignment: int | None, cited_cards: list[dict]) -> dict` returning `{"headline", "why", "play"}`.

- [ ] **Step 1: Append prompts to `app/prompts.py`**

```python
ANIMAL_TAG_SYSTEM = """You score job postings on six bipolar trait axes, each in [-1, +1]:
- social: -1 heads-down solo work ... +1 constantly people-facing
- motion: -1 building/craft ... +1 persuasion/influence/selling
- visibility: -1 behind-the-scenes ... +1 public spotlight
- environment: -1 structured/stable/big-org ... +1 ambiguous/risky/early-stage
- autonomy: -1 independent solo operator ... +1 deeply team-embedded
- north_star: -1 mission/impact-driven ... +1 comp/prestige-driven

Score each job from its title, company and any text given. Use the full range;
0.0 only when the axis is genuinely mixed or unknowable. Return one entry per
job, in the same order as given."""

ANIMAL_COPY_SYSTEM = """You write the reveal copy for a work-animal profile on a career platform.
Rules (hard):
- Animals are lateral niches. NEVER rank animals or imply one is better.
- Evidence-based: cite the actual jobs the user swiped on (given below).
- Alignment framing is strictly self-referential — drift from the user's OWN
  stated goals — and must end with one concrete, actionable play.
- Never demean ("you got worse", unflattering animal comparisons). Warm,
  specific, terse. No corporate fluff.
Write: a one-line headline (<= 10 words), a "why" (<= 40 words citing at
least one real swiped job), and a "play" (<= 25 words, imperative)."""
```

- [ ] **Step 2: Append structured-output models to `app/schemas.py`**

```python
# ── Work-animal module ─────────────────────────────────────────────


class TraitScores(BaseModel):
    social: float = Field(ge=-1, le=1)
    motion: float = Field(ge=-1, le=1)
    visibility: float = Field(ge=-1, le=1)
    environment: float = Field(ge=-1, le=1)
    autonomy: float = Field(ge=-1, le=1)
    north_star: float = Field(ge=-1, le=1)


class JobTraitTags(BaseModel):
    tags: list[TraitScores] = Field(description="One entry per job, same order as input")


class AnimalCopy(BaseModel):
    headline: str = Field(description="<= 10 words, e.g. 'You're an Owl.'")
    why: str = Field(description="<= 40 words, cites at least one swiped job")
    play: str = Field(description="<= 25 words, imperative, actionable")
```

- [ ] **Step 3: Write the failing tests** (LLM fully mocked — no network in tests)

```python
# tests/test_animal_graph.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas import AnimalCopy, JobTraitTags, TraitScores


def _mock_llm(structured_return):
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=structured_return)
    llm.with_structured_output.return_value = structured
    return llm


@pytest.mark.asyncio
async def test_tag_jobs_returns_trait_dicts_in_order():
    from app.graphs import animal as graph
    tags = JobTraitTags(tags=[
        TraitScores(social=-0.5, motion=-0.5, visibility=-0.5,
                    environment=0.0, autonomy=0.0, north_star=0.0),
        TraitScores(social=0.9, motion=0.9, visibility=0.5,
                    environment=0.0, autonomy=0.0, north_star=0.5),
    ])
    with patch.object(graph, "get_llm", return_value=_mock_llm(tags)):
        out = await graph.tag_jobs([
            {"company": "A", "title": "Backend Engineer", "url": "u1"},
            {"company": "B", "title": "Account Executive", "url": "u2"},
        ])
    assert len(out) == 2
    assert out[0]["social"] == -0.5
    assert out[1]["motion"] == 0.9


@pytest.mark.asyncio
async def test_tag_jobs_empty_is_empty_without_llm_call():
    from app.graphs import animal as graph
    with patch.object(graph, "get_llm") as mock_get:
        out = await graph.tag_jobs([])
    assert out == []
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_tag_stated_returns_single_vector():
    from app.graphs import animal as graph
    tags = JobTraitTags(tags=[
        TraitScores(social=0.2, motion=0.0, visibility=0.4,
                    environment=0.6, autonomy=0.0, north_star=-0.3),
    ])
    with patch.object(graph, "get_llm", return_value=_mock_llm(tags)):
        out = await graph.tag_stated({"target_roles": ["founder"], "goals": "build a startup"})
    assert out["environment"] == 0.6


@pytest.mark.asyncio
async def test_write_copy_returns_dict():
    from app.graphs import animal as graph
    copy = AnimalCopy(headline="You're an Owl.",
                      why="You kept the Anthropic research role and passed every sales job.",
                      play="Target deep-work roles; skip spotlight-heavy postings.")
    with patch.object(graph, "get_llm", return_value=_mock_llm(copy)):
        out = await graph.write_copy("owl", "analytical", 82, [
            {"company": "Anthropic", "title": "Research Engineer", "direction": "right"},
        ])
    assert out == {"headline": "You're an Owl.",
                   "why": "You kept the Anthropic research role and passed every sales job.",
                   "play": "Target deep-work roles; skip spotlight-heavy postings."}
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_animal_graph.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.graphs.animal'`.

- [ ] **Step 5: Write minimal implementation**

```python
# app/graphs/animal.py
"""LLM passes for the work-animal module. Everything deterministic lives in
app/services/animal.py; this module is ONLY: job trait tagging, stated-goals
tagging, and reveal copy. The classifier never touches an LLM."""

import json

from ..llm import get_llm
from ..prompts import ANIMAL_COPY_SYSTEM, ANIMAL_TAG_SYSTEM
from ..schemas import AnimalCopy, JobTraitTags


async def tag_jobs(jobs: list[dict]) -> list[dict[str, float]]:
    """Score each job on the six trait axes. One LLM call for the whole batch."""
    if not jobs:
        return []
    listing = "\n".join(
        f"{i + 1}. {j['company']} — {j['title']} ({j.get('location', '')})"
        for i, j in enumerate(jobs)
    )
    llm = get_llm(temperature=0.0).with_structured_output(JobTraitTags)
    result = await llm.ainvoke(
        f"{ANIMAL_TAG_SYSTEM}\n\nJobs:\n{listing}\n\nScore all {len(jobs)} jobs."
    )
    tags = [t.model_dump() for t in result.tags]
    # LLM count mismatch: pad with neutral, truncate extras. Never crash the deck.
    neutral = {k: 0.0 for k in tags[0]} if tags else {
        "social": 0.0, "motion": 0.0, "visibility": 0.0,
        "environment": 0.0, "autonomy": 0.0, "north_star": 0.0,
    }
    while len(tags) < len(jobs):
        tags.append(dict(neutral))
    return tags[: len(jobs)]


async def tag_stated(profile: dict) -> dict[str, float]:
    """The user's STATED goals (onboarding resume profile) as a trait vector —
    the fixed pole the alignment meter measures drift against."""
    llm = get_llm(temperature=0.0).with_structured_output(JobTraitTags)
    result = await llm.ainvoke(
        f"{ANIMAL_TAG_SYSTEM}\n\nThis is not a job posting but a candidate's "
        f"own stated career goals and profile. Score the WORK THEY SAY THEY "
        f"WANT on the same six axes (one entry):\n{json.dumps(profile)[:4000]}"
    )
    return result.tags[0].model_dump()


async def write_copy(
    animal_id: str, temperament: str, alignment: int | None, cited_cards: list[dict]
) -> dict:
    cards = "\n".join(
        f"- [{c.get('direction', '?')}] {c['company']} — {c['title']}"
        for c in cited_cards[:6]
    )
    llm = get_llm(temperature=0.4).with_structured_output(AnimalCopy)
    result = await llm.ainvoke(
        f"{ANIMAL_COPY_SYSTEM}\n\nAnimal: {animal_id}\nTemperament: {temperament}\n"
        f"Alignment vs their own stated goals: {alignment if alignment is not None else 'unknown'}/100\n"
        f"Their actual swipes:\n{cards}"
    )
    return result.model_dump()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_animal_graph.py -v`
Expected: 4 passed. (If `pytest.mark.asyncio` errors: `pytest-asyncio` is already a dev dependency; check `asyncio_mode` matches the existing async tests in this repo and copy their decorator style.)

- [ ] **Step 7: Commit**

```bash
git add app/prompts.py app/schemas.py app/graphs/animal.py tests/test_animal_graph.py
git commit -m "feat(animal): LLM trait tagging and reveal copy generation"
```

---

### Task 7: Router + registration

**Files:**
- Modify: `app/schemas.py` (append request/response models)
- Create: `app/routers/animal.py`
- Modify: `app/main.py` (import + register router)
- Test: `tests/test_animal_router.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces the API contract the frontend plan builds against:
  - `POST /api/v1/animal/deck` body `{"user_id": str, "count": int = 15}` → `{"cards": [Card]}` where Card = `{id, company, title, url, location, source, traits}`.
  - `POST /api/v1/animal/swipes` body `{"user_id": str, "swipes": [{"card": Card, "direction": "left"|"right", "decision_ms": int, "direction_changes": int}]}` → AnimalState (below) with `is_new_animal: bool` (ceremony trigger).
  - `GET /api/v1/animal/{user_id}` → AnimalState or 404.
  - `GET /api/v1/animal/{user_id}/shortlist` → `{"cards": [Card]}`.
  - AnimalState = `{"animal": str, "confidence": float, "temperament": str, "alignment": int|null, "vector": {axis: float}, "swipe_count": int, "history": [{"animal", "at"}], "copy": {"headline","why","play"}|null, "is_new_animal": bool}`.

- [ ] **Step 1: Append request/response models to `app/schemas.py`**

```python
class AnimalCard(BaseModel):
    id: str
    company: str
    title: str
    url: str
    location: str = ""
    source: str = ""
    traits: TraitScores


class AnimalDeckIn(BaseModel):
    user_id: str
    count: int = Field(default=15, ge=5, le=30)


class AnimalDeckOut(BaseModel):
    cards: list[AnimalCard]


class AnimalSwipe(BaseModel):
    card: AnimalCard
    direction: Literal["left", "right"]
    decision_ms: int = Field(ge=0)
    direction_changes: int = Field(default=0, ge=0)


class AnimalSwipesIn(BaseModel):
    user_id: str
    swipes: list[AnimalSwipe] = Field(min_length=1)


class AnimalHistoryEntry(BaseModel):
    animal: str
    at: str


class AnimalStateOut(BaseModel):
    animal: str
    confidence: float
    temperament: str
    alignment: Optional[int] = None
    vector: dict[str, float]
    swipe_count: int
    history: list[AnimalHistoryEntry] = []
    copy: Optional[AnimalCopy] = None
    is_new_animal: bool = False
```

- [ ] **Step 2: Write the failing tests** (TestClient with auth; scanner, graphs, storage all mocked)

```python
# tests/test_animal_router.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import animal as svc

HEADERS = {"X-API-Key": settings.backend_api_key}


def _card(i, **traits):
    t = dict.fromkeys(svc.AXES, 0.0) | traits
    return {"id": svc.card_id(f"https://x.com/{i}"), "company": f"Co{i}",
            "title": f"Role {i}", "url": f"https://x.com/{i}",
            "location": "Remote", "source": "seed", "traits": t}


def _swipe(card, direction, ms=1500):
    return {"card": card, "direction": direction, "decision_ms": ms,
            "direction_changes": 0}


@pytest.fixture
def client():
    return TestClient(app)


def test_deck_requires_api_key(client):
    r = client.post("/api/v1/animal/deck", json={"user_id": "u1"})
    assert r.status_code == 401


def test_deck_falls_back_to_seed_on_scan_failure(client):
    with patch("app.routers.animal.scanner.scan", new=AsyncMock(side_effect=RuntimeError)):
        r = client.post("/api/v1/animal/deck", json={"user_id": "u1"}, headers=HEADERS)
    assert r.status_code == 200
    cards = r.json()["cards"]
    assert len(cards) == 15
    assert all(c["source"] == "seed" for c in cards)


def test_deck_uses_scan_jobs_when_available(client):
    scan_result = {"total": 2, "jobs": [
        {"company": "A", "title": "Eng", "url": "https://a.com/1", "location": "", "source": "greenhouse"},
        {"company": "B", "title": "AE", "url": "https://b.com/2", "location": "", "source": "lever"},
    ], "errors": []}
    traits = [dict.fromkeys(svc.AXES, -0.5), dict.fromkeys(svc.AXES, 0.5)]
    with patch("app.routers.animal.scanner.scan", new=AsyncMock(return_value=scan_result)), \
         patch("app.routers.animal.graph.tag_jobs", new=AsyncMock(return_value=traits)):
        r = client.post("/api/v1/animal/deck", json={"user_id": "u1"}, headers=HEADERS)
    cards = r.json()["cards"]
    assert cards[0]["company"] == "A"
    assert len(cards) == 15  # topped up from seed


def test_swipes_classifies_and_persists(client):
    saved = {}
    heads_down = _card(1, social=-0.9, motion=-0.8, visibility=-0.9, autonomy=-0.5)
    spotlight = _card(2, social=0.9, motion=0.9, visibility=0.9)
    body = {"user_id": "u1", "swipes": (
        [_swipe(heads_down, "right")] * 8 + [_swipe(spotlight, "left")] * 7
    )}
    fake_copy = {"headline": "You're an Owl.", "why": "w", "play": "p"}
    with patch("app.routers.animal.storage.get_animal_state", return_value=None), \
         patch("app.routers.animal.storage.save_animal_state",
               side_effect=lambda uid, s: saved.update(s)), \
         patch("app.routers.animal.storage.append_animal_swipes"), \
         patch("app.routers.animal.storage.get_resume", return_value=None), \
         patch("app.routers.animal.graph.write_copy", new=AsyncMock(return_value=fake_copy)):
        r = client.post("/api/v1/animal/swipes", json=body, headers=HEADERS)
    assert r.status_code == 200
    out = r.json()
    assert out["animal"] == "owl"
    assert out["is_new_animal"] is True
    assert out["swipe_count"] == 15
    assert out["copy"]["headline"] == "You're an Owl."
    assert out["alignment"] is None          # no resume -> no stated goals
    assert saved["animal"] == "owl"
    assert saved["history"][0]["animal"] == "owl"


def test_swipes_same_animal_not_new(client):
    prior = {"vector": dict.fromkeys(svc.AXES, 0.0) | {"social": -0.8, "motion": -0.7,
             "visibility": -0.8, "autonomy": -0.5},
             "animal": "owl", "confidence": 0.9, "temperament": "analytical",
             "alignment": None, "stated": None, "swipe_count": 15,
             "history": [{"animal": "owl", "at": "2026-07-24T00:00:00+00:00"}],
             "copy": {"headline": "h", "why": "w", "play": "p"}}
    heads_down = _card(3, social=-0.9, motion=-0.8, visibility=-0.9, autonomy=-0.5)
    body = {"user_id": "u1", "swipes": [_swipe(heads_down, "right")]}
    fake_copy = {"headline": "Still an Owl.", "why": "w", "play": "p"}
    with patch("app.routers.animal.storage.get_animal_state", return_value=prior), \
         patch("app.routers.animal.storage.save_animal_state"), \
         patch("app.routers.animal.storage.append_animal_swipes"), \
         patch("app.routers.animal.storage.get_resume", return_value=None), \
         patch("app.routers.animal.graph.write_copy", new=AsyncMock(return_value=fake_copy)):
        r = client.post("/api/v1/animal/swipes", json=body, headers=HEADERS)
    out = r.json()
    assert out["animal"] == "owl"
    assert out["is_new_animal"] is False
    assert out["swipe_count"] == 16
    assert len(out["history"]) == 1          # no duplicate history entry


def test_get_state_404_when_never_swiped(client):
    with patch("app.routers.animal.storage.get_animal_state", return_value=None):
        r = client.get("/api/v1/animal/u1", headers=HEADERS)
    assert r.status_code == 404


def test_shortlist(client):
    cards = [_card(1), _card(2)]
    with patch("app.routers.animal.storage.get_animal_shortlist", return_value=cards):
        r = client.get("/api/v1/animal/u1/shortlist", headers=HEADERS)
    assert r.status_code == 200
    assert len(r.json()["cards"]) == 2
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_animal_router.py -v`
Expected: FAIL/ERROR — `app.routers.animal` does not exist (patch targets unresolvable), and once created the 404s fail until registered in `main.py`.

- [ ] **Step 4: Write the router**

```python
# app/routers/animal.py
"""Work-animal module: swipe deck, swipe ingestion -> classification,
current state, and the right-swipe shortlist. Right-swipe means interest
only — the apply decision stays in /evaluate."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .. import storage
from ..graphs import animal as graph
from ..schemas import (
    AnimalDeckIn, AnimalDeckOut, AnimalStateOut, AnimalSwipesIn,
)
from ..services import animal as svc
from ..services import scanner

router = APIRouter(prefix="/animal", tags=["animal"])


def _default_state() -> dict:
    return {"vector": svc.zero_vector(), "animal": None, "confidence": 0.0,
            "temperament": "decisive", "alignment": None, "stated": None,
            "swipe_count": 0, "history": [], "copy": None}


@router.post("/deck", response_model=AnimalDeckOut)
async def build_deck(body: AnimalDeckIn):
    """Deck of real jobs from the user's scan feed, LLM trait-tagged; tops up
    from the pre-tagged seed deck on cold start or scan failure."""
    jobs, traits = [], []
    try:
        result = await scanner.scan(companies=None, title_keywords=None,
                                    location_keywords=None)
        jobs = (result.get("jobs") or [])[: body.count]
        traits = await graph.tag_jobs(jobs)
    except Exception:
        jobs, traits = [], []          # seed deck carries the cold start
    return {"cards": svc.build_deck(jobs, traits, count=body.count)}


@router.post("/swipes", response_model=AnimalStateOut)
async def submit_swipes(body: AnimalSwipesIn):
    """Ingest a swipe batch: update the evolving trait vector, reclassify
    (deterministic — LLM writes copy only), recompute temperament and
    alignment, persist, and flag whether the ceremony should play."""
    state = storage.get_animal_state(body.user_id) or _default_state()
    prev_animal = state["animal"]

    vector = state["vector"]
    for s in body.swipes:
        vector = svc.update_vector(vector, s.card.traits.model_dump(), s.direction)
    swipe_count = state["swipe_count"] + len(body.swipes)

    name, confidence = svc.classify(vector, swipe_count)
    temp = svc.temperament([s.model_dump() for s in body.swipes])

    # Stated goals: tag once from the onboarding resume profile, then cache.
    stated = state.get("stated")
    if stated is None:
        resume = storage.get_resume(body.user_id)
        if resume and resume.get("profile"):
            stated = await graph.tag_stated(resume["profile"])
    align = svc.alignment(vector, stated)

    is_new = name != prev_animal
    history = state["history"]
    if is_new:
        history = history + [{"animal": name,
                              "at": datetime.now(timezone.utc).isoformat()}]

    cited = [s.card.model_dump() | {"direction": s.direction} for s in body.swipes]
    copy = await graph.write_copy(name, temp, align, cited)

    new_state = {"vector": vector, "animal": name, "confidence": confidence,
                 "temperament": temp, "alignment": align, "stated": stated,
                 "swipe_count": swipe_count, "history": history, "copy": copy}
    storage.append_animal_swipes(body.user_id, [s.model_dump() for s in body.swipes])
    storage.save_animal_state(body.user_id, new_state)

    return AnimalStateOut(**{k: v for k, v in new_state.items() if k != "stated"},
                          is_new_animal=is_new)


@router.get("/{user_id}", response_model=AnimalStateOut)
async def get_state(user_id: str):
    state = storage.get_animal_state(user_id)
    if not state or not state.get("animal"):
        raise HTTPException(404, "No animal yet — swipe a deck first")
    return AnimalStateOut(**{k: v for k, v in state.items() if k != "stated"},
                          is_new_animal=False)


@router.get("/{user_id}/shortlist", response_model=AnimalDeckOut)
async def shortlist(user_id: str):
    """Right-swiped jobs — interest only; each links into /evaluate."""
    return {"cards": storage.get_animal_shortlist(user_id)}
```

- [ ] **Step 5: Register in `app/main.py`**

Change the routers import line:

```python
from .routers import applications, career, jobs, resume, scan, users, salary, stats, animal
```

And add with the other registrations (before the employer router line):

```python
app.include_router(animal.router, prefix="/api/v1", dependencies=deps)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_animal_router.py -v`
Expected: 7 passed.

- [ ] **Step 7: Full regression**

Run: `uv run pytest`
Expected: all tests pass (new + existing career-map/rbac/stats suites).

- [ ] **Step 8: Commit**

```bash
git add app/schemas.py app/routers/animal.py app/main.py tests/test_animal_router.py
git commit -m "feat(animal): /animal router — deck, swipes, state, shortlist"
```

---

## Done means

- `uv run pytest` fully green.
- `uv run uvicorn app.main:app --port 8000` boots; `POST /api/v1/animal/deck` with the dev API key returns 15 cards (seed fallback) without any Supabase rows existing.
- Supabase SQL from Task 5 recorded for whoever owns the console.
- Frontend Plan 2 consumes exactly the contract in Task 7's Interfaces block.
