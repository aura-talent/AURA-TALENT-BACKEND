"""Employability + salary statistics — real published data only, no LLM.

The dataset is a curated JSON file compiled from published sources (SG MOE
Graduate Employment Survey, MY MOHE Graduate Tracer Study, salary guides),
each row citing its source ids. This router just serves it verbatim; all
lookup/comparison logic is client-side.
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/stats", tags=["stats"])

_DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "employability_dataset.json"


def _load_dataset() -> dict:
    with open(_DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


_dataset = _load_dataset()


@router.get("/employability/dataset")
async def employability_dataset():
    """The full curated employability/salary dataset (universities, roles,
    sources). Small enough to ship whole; the frontend filters client-side."""
    if not _dataset:
        raise HTTPException(503, "Employability dataset unavailable")
    return _dataset
