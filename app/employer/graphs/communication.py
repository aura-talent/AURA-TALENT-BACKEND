"""Agent — Communication Writer (STUB, shared).

    load_context ──> write_email

A stateless writer invoked by candidate-management, the HR supervisor, and the
offer flow to render an email's subject + body for a candidate, given the
pipeline context and a `kind` (interview_invite | follow_up | offer |
rejection | general). It decides HOW to word a message — never WHAT action to
take (that's candidate-management).

╔═══════════════════════════════════════════════════════════════════════════╗
║  AGENT SEAM — replace write_email with a                                   ║
║  get_llm().with_structured_output(CommsDraftOut) call over the context.    ║
║  The route (POST /employer/comms/generate) and contract (CommsGenerate →   ║
║  CommsDraftOut) are done. Keep the output shape (CommsDraftOut).           ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""

from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..schemas import CommsDraftOut


class CommunicationState(TypedDict, total=False):
    # inputs
    employer_id: str
    candidate_user_id: str
    job_id: Optional[str]
    kind: str
    instructions: Optional[str]
    # loaded
    context: Optional[dict]
    # produced
    draft: CommsDraftOut


async def load_context(state: CommunicationState) -> dict:
    if state.get("job_id"):
        from ..services.context import build_candidate_context
        return {"context": build_candidate_context(
            state["job_id"], state["candidate_user_id"], state["employer_id"],
        )}
    return {"context": None}


async def write_email(state: CommunicationState) -> dict:
    # AGENT SEAM: replace with an LLM draft. Placeholder keeps the flow working.
    ctx = state.get("context") or {}
    candidate = (ctx.get("candidate") or {})
    name = candidate.get("full_name") or "there"
    job = (ctx.get("job") or {})
    role = job.get("title") or "the role"
    kind = state.get("kind", "general")
    subjects = {
        "interview_invite": f"Interview invitation — {role}",
        "follow_up": f"Following up on your application — {role}",
        "offer": f"Your offer for {role}",
        "rejection": f"Update on your application — {role}",
        "general": f"Regarding {role}",
    }
    subject = subjects.get(kind, subjects["general"])
    body = (
        f"Hi {name},\n\n"
        f"[Placeholder {kind} email for {role}. Replace communication.write_email "
        f"with real LLM drafting over the candidate context.]\n\n"
        "Best regards,\nThe hiring team"
    )
    return {"draft": CommsDraftOut(subject=subject, body=body)}


def build_communication_graph():
    g = StateGraph(CommunicationState)
    g.add_node("load_context", load_context)
    g.add_node("write_email", write_email)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "write_email")
    g.add_edge("write_email", END)
    return g.compile()


communication_graph = build_communication_graph()
