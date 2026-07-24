import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ...auth import verify_user_role
from ...logging_config import logger
from .. import storage
from ..graphs.hr_chat import build_hr_chat_agent
from ..schemas import ChatMessageIn, ChatThreadCreate

router = APIRouter(prefix="/chat", tags=["employer:chat"])

# Friendly progress labels for each hr_chat tool (see graphs/hr_chat.py) —
# shown live while Aura works instead of a static "thinking" spinner.
_TOOL_LABELS = {
    "get_overview": "Checking your pipeline overview...",
    "get_job": "Looking up job details...",
    "get_candidate": "Looking up candidate details...",
    "create_job": "Drafting the new job listing...",
    "score_candidate": "Triggering candidate evaluation...",
    "source_candidates": "Sourcing new candidates...",
    "propose_email": "Drafting an email...",
    "propose_offer": "Drafting an offer...",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _text(content) -> str:
    """Normalize an AIMessage.content into plain text. Anthropic returns a
    plain str; Gemini/Vertex returns a list of content-block dicts
    (text/thought/tool-use parts) — join just the text parts so what gets
    stored and replayed as history is always readable, provider-agnostic
    text, not a stringified block list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)


def _require_owned_thread(thread_id: str, employer_id: str) -> dict:
    verify_user_role(employer_id, ["employer"])
    thread = storage.get_chat_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Chat thread not found")
    if thread["employer_id"] != employer_id:
        raise HTTPException(403, "Thread belongs to another employer")
    return thread


@router.get("/threads")
async def list_threads(employer_id: str):
    verify_user_role(employer_id, ["employer"])
    return storage.list_chat_threads(employer_id)


@router.post("/threads")
async def create_thread(body: ChatThreadCreate):
    verify_user_role(body.employer_id, ["employer"])
    return storage.create_chat_thread(body.employer_id, body.title)


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str, employer_id: str):
    _require_owned_thread(thread_id, employer_id)
    storage.delete_chat_thread(thread_id)
    return {"ok": True}


@router.get("/thread/{thread_id}/messages")
async def list_messages(thread_id: str, employer_id: str):
    _require_owned_thread(thread_id, employer_id)
    return storage.list_chat_messages(thread_id)


@router.post("/thread/{thread_id}/messages")
async def send_message(thread_id: str, body: ChatMessageIn):
    """Post a message to Aura and get her reply (non-streaming). Any drafted
    email/offer is staged as a suggested_actions row (returned in
    proposed_action_ids) — the agent never sends anything itself; confirm via
    POST /suggested-actions/{id}/execute to actually act on it."""
    _require_owned_thread(thread_id, body.employer_id)

    is_first_message = not storage.list_chat_messages(thread_id)
    storage.create_chat_message({
        "thread_id": thread_id, "role": "user", "content": body.content,
    })
    if is_first_message:
        storage.update_chat_thread(thread_id, {"title": body.content[:60]})

    history = [
        (m["role"], m["content"])
        for m in storage.list_chat_messages(thread_id)
        if m["role"] in ("user", "assistant") and m["content"]
    ]

    agent, proposed_action_ids = build_hr_chat_agent(body.employer_id)
    try:
        result = await agent.ainvoke({"messages": history})
        reply = _text(result["messages"][-1].content)
    except Exception:
        logger.exception(f"HR chat agent failed for thread {thread_id}")
        reply = "Sorry, I hit an error trying to answer that — please try again."

    saved = storage.create_chat_message({
        "thread_id": thread_id, "role": "assistant", "content": reply,
        "proposed_action_ids": proposed_action_ids,
    })
    return saved


@router.post("/thread/{thread_id}/messages/stream")
async def send_message_stream(thread_id: str, body: ChatMessageIn):
    """Same as POST /messages but streams SSE progress events (what tool
    Aura's using / that she's thinking) while she works, then a final
    `result` event carrying the saved assistant message — same shape the
    non-streaming route returns, so the frontend renders identically once
    the stream ends."""
    _require_owned_thread(thread_id, body.employer_id)

    is_first_message = not storage.list_chat_messages(thread_id)
    storage.create_chat_message({
        "thread_id": thread_id, "role": "user", "content": body.content,
    })
    if is_first_message:
        storage.update_chat_thread(thread_id, {"title": body.content[:60]})

    history = [
        (m["role"], m["content"])
        for m in storage.list_chat_messages(thread_id)
        if m["role"] in ("user", "assistant") and m["content"]
    ]

    async def generate():
        agent, proposed_action_ids = build_hr_chat_agent(body.employer_id)
        final_content = None
        try:
            async for event in agent.astream_events({"messages": history}, version="v2"):
                et = event["event"]
                name = event.get("name", "")
                if et == "on_chat_model_start":
                    yield _sse("progress", {"node": "thinking", "message": "Thinking..."})
                elif et == "on_tool_start":
                    label = _TOOL_LABELS.get(name, f"Running {name}...")
                    yield _sse("progress", {"node": name, "message": label})
                elif et == "on_chat_model_end":
                    output = event.get("data", {}).get("output")
                    content = getattr(output, "content", None)
                    if content is not None:
                        final_content = content
            reply = _text(final_content) if final_content is not None else (
                "Sorry, I didn't get a clear answer that time — try again."
            )
        except Exception:
            logger.exception(f"HR chat agent stream failed for thread {thread_id}")
            reply = "Sorry, I hit an error trying to answer that — please try again."

        saved = storage.create_chat_message({
            "thread_id": thread_id, "role": "assistant", "content": reply,
            "proposed_action_ids": proposed_action_ids,
        })
        yield _sse("result", saved)

    return StreamingResponse(generate(), media_type="text/event-stream")
