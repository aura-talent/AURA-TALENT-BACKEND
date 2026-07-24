from fastapi import APIRouter

from ...auth import verify_user_role
from ...logging_config import logger
from .. import storage
from ..graphs.hr_chat import build_hr_chat_agent
from ..schemas import ChatMessageIn

router = APIRouter(prefix="/chat", tags=["employer:chat"])


@router.get("/thread")
async def get_thread(employer_id: str):
    """Get (or create) the employer's standing Aura chat thread."""
    verify_user_role(employer_id, ["employer"])
    return storage.get_or_create_chat_thread(employer_id)


@router.get("/thread/{thread_id}/messages")
async def list_messages(thread_id: str, employer_id: str):
    verify_user_role(employer_id, ["employer"])
    return storage.list_chat_messages(thread_id)


@router.post("/thread/{thread_id}/messages")
async def send_message(thread_id: str, body: ChatMessageIn):
    """Post a message to Aura and get her reply. Any drafted email/offer is
    staged as a suggested_actions row (returned in proposed_action_ids) —
    the agent never sends anything itself; confirm via
    POST /suggested-actions/{id}/execute to actually act on it."""
    verify_user_role(body.employer_id, ["employer"])

    storage.create_chat_message({
        "thread_id": thread_id, "role": "user", "content": body.content,
    })

    history = [
        (m["role"], m["content"])
        for m in storage.list_chat_messages(thread_id)
        if m["role"] in ("user", "assistant") and m["content"]
    ]

    agent, proposed_action_ids = build_hr_chat_agent(body.employer_id)
    try:
        result = await agent.ainvoke({"messages": history})
        reply = result["messages"][-1].content
    except Exception:
        logger.exception(f"HR chat agent failed for thread {thread_id}")
        reply = "Sorry, I hit an error trying to answer that — please try again."

    saved = storage.create_chat_message({
        "thread_id": thread_id, "role": "assistant", "content": reply,
        "proposed_action_ids": proposed_action_ids,
    })
    return saved
