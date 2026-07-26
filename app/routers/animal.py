# app/routers/animal.py
"""Work-animal module: swipe deck, swipe ingestion -> classification,
current state, and the right-swipe shortlist. Right-swipe means interest
only — the apply decision stays in /evaluate."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .. import storage
from ..graphs import animal as graph
from ..logging_config import logger
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
    except Exception as exc:
        logger.warning(f"animal deck: scan/tagging failed, using seed deck: {exc}")
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
