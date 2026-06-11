"""Resume graphs: parse an uploaded resume into clean markdown + profile,
and generate JD-specific customization suggestions (Block E logic)."""

import io
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..llm import get_llm
from ..prompts import RESUME_PARSE_SYSTEM, RESUME_SUGGEST_SYSTEM
from ..schemas import ParsedResume
from ..services.jd_fetch import fetch_jd_text

# ── File extraction (pdf / docx / txt / md) ─────────────────────────


def extract_text(filename: str, content: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if name.endswith(".docx"):
        from docx import Document

        doc = Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    return content.decode("utf-8", errors="replace")


# ── Parse graph ─────────────────────────────────────────────────────


class ParseState(TypedDict, total=False):
    raw_text: str
    parsed: ParsedResume


async def parse_resume_node(state: ParseState) -> dict:
    llm = get_llm().with_structured_output(ParsedResume)
    parsed = await llm.ainvoke([
        ("system", RESUME_PARSE_SYSTEM),
        ("human", state["raw_text"]),
    ])
    return {"parsed": parsed}


def build_parse_graph():
    g = StateGraph(ParseState)
    g.add_node("parse_resume", parse_resume_node)
    g.add_edge(START, "parse_resume")
    g.add_edge("parse_resume", END)
    return g.compile()


parse_graph = build_parse_graph()


# ── Suggestion graph ────────────────────────────────────────────────


class SuggestState(TypedDict, total=False):
    resume_md: str
    jd_text: Optional[str]
    jd_url: Optional[str]
    suggestions_markdown: str


async def fetch_jd(state: SuggestState) -> dict:
    if state.get("jd_text"):
        return {}
    if not state.get("jd_url"):
        raise ValueError("Provide jd_text or jd_url")
    return {"jd_text": await fetch_jd_text(state["jd_url"])}


async def suggest_node(state: SuggestState) -> dict:
    llm = get_llm(temperature=0.4)
    msg = await llm.ainvoke([
        ("system", RESUME_SUGGEST_SYSTEM),
        ("human",
         f"## Resume\n\n{state['resume_md']}\n\n"
         f"## Target job description\n\n{state['jd_text']}"),
    ])
    return {"suggestions_markdown": msg.content}


def build_suggest_graph():
    g = StateGraph(SuggestState)
    g.add_node("fetch_jd", fetch_jd)
    g.add_node("suggest", suggest_node)
    g.add_edge(START, "fetch_jd")
    g.add_edge("fetch_jd", "suggest")
    g.add_edge("suggest", END)
    return g.compile()


suggest_graph = build_suggest_graph()
