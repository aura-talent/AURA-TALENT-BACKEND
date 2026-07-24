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

import json
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.llm import get_llm

from ..schemas import CommsDraftOut
from ..prompts import COMMUNICATION_GENERAL_PROMPT


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
    ctx = state.get("context") or {}
    candidate = (ctx.get("candidate") or {})
    name = candidate.get("full_name") or "there"
    job = (ctx.get("job") or {})
    role = job.get("title") or "the role"
    kind = state.get("kind", "general")
    profile = ctx.get("profile") or {}
    company_name = profile.get("company_name") or "our company"

    # Voice grounding: give the model the employer's own words so the email
    # sounds like this company, not a generic template.
    voice_parts = []
    if profile.get("about"):
        voice_parts.append(f"About the company: {profile['about']}")
    if profile.get("culture_values"):
        voice_parts.append(f"Culture/values: {', '.join(profile['culture_values'])}")
    voice_block = "\n".join(voice_parts) or "No company voice details available — keep it neutral and professional."

    # Anything else the context builder has (stage, evaluation, offer) that
    # helps the model ground specifics instead of inventing them.
    situation = {
        "application_stage": (ctx.get("application") or {}).get("stage"),
        "match_summary": (ctx.get("evaluation") or {}).get("match_summary"),
        "offer_status": (ctx.get("offer") or {}).get("status"),
    }
    situation_block = json.dumps({k: v for k, v in situation.items() if v}, indent=2)

    llm = get_llm().with_structured_output(CommsDraftOut)
    result = await llm.ainvoke([
        ("system", COMMUNICATION_GENERAL_PROMPT),
        ("human", f"""
            kind: {kind}
            candidate_name: {name}
            role: {role}
            company_name: {company_name}

            {voice_block}

            context (pipeline situation, use only what's relevant):
            {situation_block}

            Employer instructions (if any, follow these on top of the above): {state.get("instructions") or "none"}
        """),
    ])
    
    subject = result.subject
    body = result.body
    
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
