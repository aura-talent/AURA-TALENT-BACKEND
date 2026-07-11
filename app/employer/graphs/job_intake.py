"""Agent 1 — Job Intake. Backs JobEditor's creation assists
(CreationAssist = "aura" | "url") and the interview-questions customize page.

    fetch_source ──> draft_job ──> generate_interview_questions

Everything returned is a draft for the editor — nothing persists until the
employer saves through POST /employer/jobs.
"""

from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ...llm import get_llm
from ...services.jd_fetch import fetch_jd_text
from ..prompts import INTERVIEW_QUESTIONS_SYSTEM, JOB_DRAFT_SYSTEM
from ..schemas import InterviewQuestionsOut, JobDraftOut


class JobIntakeState(TypedDict, total=False):
    # inputs
    mode: str                  # "aura" (freeform brief) | "url" (import posting)
    brief: Optional[str]
    jd_url: Optional[str]
    question_count: int
    # produced
    source_text: str
    draft: JobDraftOut
    interview_questions: list[str]


async def fetch_source(state: JobIntakeState) -> dict:
    if state["mode"] == "url":
        if not state.get("jd_url"):
            raise ValueError("Provide jd_url for url mode")
        return {"source_text": await fetch_jd_text(state["jd_url"])}
    if not state.get("brief"):
        raise ValueError("Provide a hiring brief for aura mode")
    return {"source_text": state["brief"]}


async def draft_job(state: JobIntakeState) -> dict:
    llm = get_llm(temperature=0.4).with_structured_output(JobDraftOut)
    origin = "scraped job posting" if state["mode"] == "url" else "employer hiring brief"
    result = await llm.ainvoke([
        ("system", JOB_DRAFT_SYSTEM),
        ("human", f"## Source ({origin})\n\n{state['source_text']}"),
    ])
    return {"draft": result}


async def generate_interview_questions(state: JobIntakeState) -> dict:
    draft = state["draft"]
    n = state.get("question_count") or 5
    llm = get_llm(temperature=0.4).with_structured_output(InterviewQuestionsOut)
    result = await llm.ainvoke([
        ("system", INTERVIEW_QUESTIONS_SYSTEM),
        ("human",
         f"Write exactly {n} questions.\n\n"
         f"# Job: {draft.title}\n\n{draft.description}\n\n"
         f"Keywords: {', '.join(draft.keywords)}"),
    ])
    return {"interview_questions": result.questions[:n]}


def build_job_intake_graph():
    g = StateGraph(JobIntakeState)
    g.add_node("fetch_source", fetch_source)
    g.add_node("draft_job", draft_job)
    g.add_node("generate_interview_questions", generate_interview_questions)
    g.add_edge(START, "fetch_source")
    g.add_edge("fetch_source", "draft_job")
    g.add_edge("draft_job", "generate_interview_questions")
    g.add_edge("generate_interview_questions", END)
    return g.compile()


job_intake_graph = build_job_intake_graph()
