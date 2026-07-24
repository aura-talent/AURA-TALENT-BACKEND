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


@pytest.mark.asyncio
async def test_tag_jobs_pads_and_truncates_on_count_mismatch():
    from app.graphs import animal as graph
    one_tag = JobTraitTags(tags=[
        TraitScores(social=-0.5, motion=-0.5, visibility=-0.5,
                    environment=0.0, autonomy=0.0, north_star=0.0),
    ])
    jobs3 = [{"company": c, "title": "T", "url": c} for c in ("A", "B", "C")]
    # LLM returned 1 tag for 3 jobs -> real tag kept, 2 neutral pads
    with patch.object(graph, "get_llm", return_value=_mock_llm(one_tag)):
        out = await graph.tag_jobs(jobs3)
    assert len(out) == 3
    assert out[0]["social"] == -0.5
    assert all(v == 0.0 for v in out[1].values())
    assert all(v == 0.0 for v in out[2].values())
    # Truncate direction: LLM returned 3 tags for 1 job -> extras dropped
    three_tags = JobTraitTags(tags=[
        TraitScores(social=-0.5, motion=-0.5, visibility=-0.5,
                    environment=0.0, autonomy=0.0, north_star=0.0),
        TraitScores(social=0.9, motion=0.9, visibility=0.9,
                    environment=0.0, autonomy=0.0, north_star=0.0),
        TraitScores(social=0.1, motion=0.1, visibility=0.1,
                    environment=0.0, autonomy=0.0, north_star=0.0),
    ])
    with patch.object(graph, "get_llm", return_value=_mock_llm(three_tags)):
        out1 = await graph.tag_jobs([jobs3[0]])
    assert len(out1) == 1
    assert out1[0]["social"] == -0.5   # first tag kept, surplus discarded
