"""Career path graph — the Career Path Navigator.

Compares the candidate's resume/profile against their full evaluation history
to map realistic next career moves, grounded in actual data.

    gather_signals ──> map_routes ──> compose_report
"""

from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from ..llm import get_llm
from ..prompts import CAREER_PATH_SYSTEM
from ..schemas import CareerPathPlan


class CareerPathState(TypedDict, total=False):
    resume_md: str
    profile: dict
    evaluations: list[dict]  # rows from storage.list_evaluations
    goal: Optional[str]
    horizon: Optional[str]
    data_brief: str
    plan: CareerPathPlan
    report_markdown: str


def _summarize_evaluation(ev: dict) -> str:
    scores = ev.get("scores", {})
    return (
        f"- {ev.get('company')} — {ev.get('role')} "
        f"[{ev.get('archetype', 'n/a')}] | global {ev.get('score')}/5 "
        f"(match_cv {scores.get('match_cv')}, alignment {scores.get('alignment')}, "
        f"comp {scores.get('comp')}, culture {scores.get('culture')}, "
        f"red_flags {scores.get('red_flags')}) | "
        f"verdict: {ev.get('recommendation', 'n/a')}"
    )


def gather_signals(state: CareerPathState) -> dict:
    """Distill every data point — profile + the whole evaluation history — into
    a compact brief the model reasons over."""
    profile = state.get("profile") or {}
    lines = []

    headline = profile.get("headline")
    yoe = profile.get("years_of_experience")
    top_skills = profile.get("top_skills") or []
    target_archetypes = profile.get("target_archetypes") or []
    if headline:
        lines.append(f"Headline: {headline}")
    if yoe is not None:
        lines.append(f"Years of experience: {yoe}")
    if top_skills:
        lines.append(f"Top skills: {', '.join(top_skills)}")
    if target_archetypes:
        lines.append(f"Stated target archetypes: {', '.join(target_archetypes)}")

    evaluations = state.get("evaluations") or []
    if evaluations:
        lines.append(f"\nEvaluation history ({len(evaluations)} offers):")
        lines.extend(_summarize_evaluation(ev) for ev in evaluations)
    else:
        lines.append(
            "\nEvaluation history: none yet — base the analysis on the resume "
            "and say so."
        )

    if state.get("goal"):
        lines.append(f"\nCandidate's stated goal: {state['goal']}")
    if state.get("horizon"):
        lines.append(f"Planning horizon: {state['horizon']}")

    return {"data_brief": "\n".join(lines)}


async def map_routes(state: CareerPathState) -> dict:
    llm = get_llm(temperature=0.3).with_structured_output(CareerPathPlan)
    plan = await llm.ainvoke([
        ("system", CAREER_PATH_SYSTEM),
        ("human",
         f"## Candidate resume\n\n{state['resume_md']}\n\n"
         f"## Data signals\n\n{state['data_brief']}"),
    ])
    return {"plan": plan}


def compose_report(state: CareerPathState) -> dict:
    plan = state["plan"]
    blocks = []
    for i, route in enumerate(plan.routes, 1):
        gaps = "\n".join(f"  - {g}" for g in route.skill_gaps) or "  - (none identified)"
        if route.moves:
            move_rows = "\n".join(
                f"| {m.category} | {m.action} | {m.why} | {m.effort} | {m.timeframe} |"
                for m in route.moves
            )
            moves_md = (
                "**Moves to climb this route:**\n\n"
                "| Type | Action | Why it works | Effort | Timeframe |\n"
                "|------|--------|--------------|--------|-----------|\n"
                f"{move_rows}\n"
            )
        else:
            moves_md = "**Moves to climb this route:** (none identified)\n"
        blocks.append(
            f"### {i}. {route.title}  \n"
            f"**Archetype:** {route.archetype} · **Fit:** {route.fit}/5 · "
            f"**Horizon:** {route.time_horizon}\n\n"
            f"{route.rationale}\n\n"
            f"**Skill gaps to close:**\n{gaps}\n\n"
            f"{moves_md}"
        )

    routes_md = "\n".join(blocks)
    report = f"""# Career Path Navigator

> {plan.current_assessment}

**🎯 Do this first:** {plan.first_move}

---

## Realistic routes from here

{routes_md}

---

## Recommended next move
**{plan.recommended_route}**
"""
    return {"report_markdown": report}


def build_career_path_graph():
    g = StateGraph(CareerPathState)
    g.add_node("gather_signals", gather_signals)
    g.add_node("map_routes", map_routes)
    g.add_node("compose_report", compose_report)
    g.add_edge(START, "gather_signals")
    g.add_edge("gather_signals", "map_routes")
    g.add_edge("map_routes", "compose_report")
    g.add_edge("compose_report", END)
    return g.compile()


career_path_graph = build_career_path_graph()
