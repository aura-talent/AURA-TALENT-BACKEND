import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .. import storage
from ..auth import verify_user_role
from ..graphs.career_map import career_map_graph, expand_node, merge_expansion
from ..graphs.career_path import career_path_graph
from ..logging_config import log_error, logger
from ..schemas import (
    CareerMapExpandIn, CareerMapIn, CareerMapOut, CareerPathIn, CareerPathOut,
)

router = APIRouter(prefix="/career", tags=["career"])

_PATH_NODE_LABELS = {
    "gather_signals": "Gathering your resume and evaluation history...",
    "map_routes": "Mapping realistic career routes...",
    "compose_report": "Composing your career path...",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _path_state(body: CareerPathIn) -> tuple[dict, int]:
    """Build the graph input by comparing every piece of the candidate's data:
    their parsed resume/profile plus their full evaluation history."""
    verify_user_role(body.user_id, ["candidate"])
    resume = storage.get_resume(body.user_id)
    if not resume:
        raise HTTPException(404, "Upload a resume first")

    evaluations = storage.list_evaluations(body.user_id)
    state = {
        "resume_md": resume["markdown"],
        "profile": resume.get("profile") or {},
        "evaluations": evaluations,
        "goal": body.goal,
        "horizon": body.horizon,
    }
    return state, len(evaluations)


def _path_out(body: CareerPathIn, result: dict, considered: int) -> CareerPathOut:
    plan = result["plan"]
    return CareerPathOut(
        user_id=body.user_id,
        current_assessment=plan.current_assessment,
        routes=plan.routes,
        recommended_route=plan.recommended_route,
        first_move=plan.first_move,
        evaluations_considered=considered,
        report_markdown=result["report_markdown"],
    )


@router.post("/path", response_model=CareerPathOut)
async def career_path(body: CareerPathIn):
    """Generate a realistic career path for the candidate by comparing their
    resume/profile against their entire evaluation history (Career Path
    Navigator). Returns 3-5 grounded routes and a recommended next move."""
    state, considered = _path_state(body)
    logger.info(
        f"🧭 Career path for user {body.user_id} ({considered} evaluations considered)"
    )
    try:
        result = await career_path_graph.ainvoke(state)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _path_out(body, result, considered)


@router.post("/path/stream")
async def career_path_stream(body: CareerPathIn):
    """Same as /path but streams SSE progress events, then the final result."""
    state, considered = _path_state(body)

    async def generate():
        try:
            final_result = None
            async for event in career_path_graph.astream_events(state, version="v2"):
                if event["event"] == "on_chain_start" and event["name"] in _PATH_NODE_LABELS:
                    yield _sse("progress", {
                        "node": event["name"],
                        "message": _PATH_NODE_LABELS[event["name"]],
                    })
                if event["event"] == "on_chain_end" and event.get("name") == "LangGraph":
                    final_result = event.get("data", {}).get("output")

            if not final_result:
                final_result = await career_path_graph.ainvoke(state)

            yield _sse("result", _path_out(body, final_result, considered).model_dump())
        except ValueError as e:
            log_error(e, context="career_path_stream")
            yield _sse("error", {"detail": str(e)})
        except Exception as e:
            log_error(e, context="career_path_stream")
            yield _sse("error", {"detail": "Internal server error"})

    return StreamingResponse(generate(), media_type="text/event-stream")


_MAP_NODE_LABELS = {
    "gather_signals": "Gathering your resume and evaluation history...",
    "map_graph": "Mapping your career space...",
    "normalize": "Validating the map...",
}


def _map_state(user_id: str) -> dict:
    verify_user_role(user_id, ["candidate"])
    resume = storage.get_resume(user_id)
    if not resume:
        raise HTTPException(404, "Upload a resume first")
    return {
        "resume_md": resume["markdown"],
        "profile": resume.get("profile") or {},
        "evaluations": storage.list_evaluations(user_id),
    }


def _map_out(user_id: str, draft) -> CareerMapOut:
    return CareerMapOut(
        **draft.model_dump(),
        user_id=user_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/map", response_model=CareerMapOut)
async def career_map(body: CareerMapIn):
    """Return the stored career map, generating (and persisting) it if absent
    or if force_refresh is set."""
    if not body.force_refresh:
        stored = storage.get_career_map(body.user_id)
        if stored:
            return CareerMapOut(**stored)
    state = _map_state(body.user_id)
    logger.info(f"🗺️ Career map for user {body.user_id}")
    try:
        result = await career_map_graph.ainvoke(state)
    except ValueError as e:
        raise HTTPException(422, str(e))
    out = _map_out(body.user_id, result["draft"])
    storage.save_career_map(body.user_id, out.model_dump())
    return out


@router.post("/map/stream")
async def career_map_stream(body: CareerMapIn):
    """Same as /map but SSE: stage progress events, then the result. A cached
    map is yielded immediately as the result event."""
    if not body.force_refresh:
        stored = storage.get_career_map(body.user_id)
        if stored:
            async def cached():
                yield _sse("result", stored)
            return StreamingResponse(cached(), media_type="text/event-stream")

    state = _map_state(body.user_id)

    async def generate():
        try:
            final_result = None
            async for event in career_map_graph.astream_events(state, version="v2"):
                if event["event"] == "on_chain_start" and event["name"] in _MAP_NODE_LABELS:
                    yield _sse("progress", {
                        "node": event["name"],
                        "message": _MAP_NODE_LABELS[event["name"]],
                    })
                if event["event"] == "on_chain_end" and event.get("name") == "LangGraph":
                    final_result = event.get("data", {}).get("output")

            if not final_result:
                final_result = await career_map_graph.ainvoke(state)

            out = _map_out(body.user_id, final_result["draft"])
            storage.save_career_map(body.user_id, out.model_dump())
            yield _sse("result", out.model_dump())
        except ValueError as e:
            log_error(e, context="career_map_stream")
            yield _sse("error", {"detail": str(e)})
        except Exception as e:
            log_error(e, context="career_map_stream")
            yield _sse("error", {"detail": "Internal server error"})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/map/expand", response_model=CareerMapOut)
async def career_map_expand(body: CareerMapExpandIn):
    """Grow 2-4 child roles beyond one expandable leaf node; persist the merge."""
    verify_user_role(body.user_id, ["candidate"])
    stored = storage.get_career_map(body.user_id)
    if not stored:
        raise HTTPException(404, "Generate a career map first")
    if not any(n["id"] == body.node_id for n in stored["nodes"]):
        raise HTTPException(404, f"Node '{body.node_id}' not in map")
    logger.info(f"🌱 Expanding career map node {body.node_id} for user {body.user_id}")
    expansion = await expand_node(stored, body.node_id)
    merged = merge_expansion(stored, expansion, body.node_id)
    storage.save_career_map(body.user_id, merged)
    return CareerMapOut(**merged)
