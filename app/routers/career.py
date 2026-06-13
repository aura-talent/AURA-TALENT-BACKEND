import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .. import storage
from ..auth import verify_user_role
from ..graphs.career_path import career_path_graph
from ..logging_config import log_error, logger
from ..schemas import CareerPathIn, CareerPathOut

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
