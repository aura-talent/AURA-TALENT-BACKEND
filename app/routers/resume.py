import json
import re

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse

from .. import storage
from ..graphs.resume import extract_text, generate_graph, parse_graph, suggest_graph
from ..schemas import (
    GenerateResumeIn,
    GenerateResumeOut,
    ResumeOut,
    ResumePdfIn,
    ResumeTextIn,
    SuggestIn,
    SuggestOut,
)
from ..services.jd_fetch import JDFetchError
from ..services.pdf import markdown_to_pdf
from ..logging_config import log_error

_SUGGEST_NODE_LABELS = {
    "fetch_jd": "Fetching job description...",
    "suggest": "Generating tailored suggestions...",
}

_GENERATE_NODE_LABELS = {
    "fetch_jd": "Fetching job description...",
    "tailor_resume": "Writing your tailored resume...",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

router = APIRouter(prefix="/resume", tags=["resume"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@router.post("/upload", response_model=ResumeOut)
async def upload_resume(user_id: str = Form(...), file: UploadFile = File(...)):
    """Upload a resume file (PDF, DOCX, TXT, or MD); parsed to clean markdown."""
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 5 MB)")
    raw = extract_text(file.filename or "resume.txt", content)
    if len(raw.strip()) < 100:
        raise HTTPException(422, "Could not extract enough text from the file")
    return await _parse_and_save(user_id, raw)


@router.post("/text", response_model=ResumeOut)
async def submit_resume_text(body: ResumeTextIn):
    """Submit resume as raw text (e.g. pasted into the website)."""
    if len(body.text.strip()) < 100:
        raise HTTPException(422, "Resume text too short")
    return await _parse_and_save(body.user_id, body.text)


@router.get("/{user_id}", response_model=ResumeOut)
async def get_resume(user_id: str):
    resume = storage.get_resume(user_id)
    if not resume:
        raise HTTPException(404, "No resume found for this user")
    return ResumeOut(**resume)


@router.post("/suggestions", response_model=SuggestOut)
async def resume_suggestions(body: SuggestIn):
    """JD-specific resume improvement plan (career-ops Block E)."""
    resume = storage.get_resume(body.user_id)
    if not resume:
        raise HTTPException(404, "Upload a resume first")
    try:
        result = await suggest_graph.ainvoke({
            "resume_md": resume["markdown"],
            "jd_text": body.jd_text,
            "jd_url": body.jd_url,
        })
    except (JDFetchError, ValueError) as e:
        raise HTTPException(422, str(e))
    return SuggestOut(suggestions_markdown=result["suggestions_markdown"])


@router.post("/suggestions/stream")
async def resume_suggestions_stream(body: SuggestIn):
    """Same as /suggestions but streams SSE progress events, then the final result."""
    resume = storage.get_resume(body.user_id)
    if not resume:
        raise HTTPException(404, "Upload a resume first")

    async def generate():
        try:
            async for event in suggest_graph.astream_events(
                {
                    "resume_md": resume["markdown"],
                    "jd_text": body.jd_text,
                    "jd_url": body.jd_url,
                },
                version="v2",
            ):
                if event["event"] == "on_chain_start" and event["name"] in _SUGGEST_NODE_LABELS:
                    yield _sse("progress", {
                        "node": event["name"],
                        "message": _SUGGEST_NODE_LABELS[event["name"]],
                    })

            result = await suggest_graph.ainvoke({
                "resume_md": resume["markdown"],
                "jd_text": body.jd_text,
                "jd_url": body.jd_url,
            })
            yield _sse("result", {"suggestions_markdown": result["suggestions_markdown"]})
        except (JDFetchError, ValueError) as e:
            log_error(e, context="resume_suggestions_stream")
            yield _sse("error", {"detail": str(e)})
        except Exception as e:
            log_error(e, context="resume_suggestions_stream")
            yield _sse("error", {"detail": "Internal server error"})

    return StreamingResponse(generate(), media_type="text/event-stream")


def _generate_state(body: GenerateResumeIn) -> dict:
    """Resolve the graph input: master resume + JD (direct or from a prior
    evaluation) + optional user instructions."""
    resume = storage.get_resume(body.user_id)
    if not resume:
        raise HTTPException(404, "Upload a resume first")

    jd_text, jd_url, keywords_hint = body.jd_text, body.jd_url, None
    if body.evaluation_id is not None:
        ev = storage.get_evaluation(body.user_id, body.evaluation_id)
        if not ev:
            raise HTTPException(404, f"Evaluation {body.evaluation_id} not found")
        jd_url = jd_url or ev.get("jd_url")
        keywords_hint = ev.get("keywords") or None
    if not jd_text and not jd_url:
        raise HTTPException(422, "Provide jd_text, jd_url, or an evaluation_id with a stored JD URL")

    return {
        "resume_md": resume["markdown"],
        "jd_text": jd_text,
        "jd_url": jd_url,
        "keywords_hint": keywords_hint,
        "extra_instructions": body.extra_instructions,
    }


@router.post("/generate", response_model=GenerateResumeOut)
async def generate_resume(body: GenerateResumeIn):
    """Generate a complete resume tailored to a JD (full rewrite, not just
    suggestions). Pair with POST /resume/pdf to export the result."""
    state = _generate_state(body)
    try:
        result = await generate_graph.ainvoke(state)
    except (JDFetchError, ValueError) as e:
        raise HTTPException(422, str(e))
    t = result["tailored"]
    return GenerateResumeOut(
        tailored_markdown=t.tailored_markdown,
        change_summary=t.change_summary,
        keywords_covered=t.keywords_covered,
    )


@router.post("/generate/stream")
async def generate_resume_stream(body: GenerateResumeIn):
    """Same as /generate but streams SSE progress events, then the final result."""
    state = _generate_state(body)

    async def generate():
        try:
            final_result = None
            async for event in generate_graph.astream_events(state, version="v2"):
                if event["event"] == "on_chain_start" and event["name"] in _GENERATE_NODE_LABELS:
                    yield _sse("progress", {
                        "node": event["name"],
                        "message": _GENERATE_NODE_LABELS[event["name"]],
                    })
                if event["event"] == "on_chain_end" and event.get("name") == "LangGraph":
                    final_result = event.get("data", {}).get("output")

            if not final_result:
                final_result = await generate_graph.ainvoke(state)

            t = final_result["tailored"]
            yield _sse("result", GenerateResumeOut(
                tailored_markdown=t.tailored_markdown,
                change_summary=t.change_summary,
                keywords_covered=t.keywords_covered,
            ).model_dump())
        except (JDFetchError, ValueError) as e:
            log_error(e, context="generate_resume_stream")
            yield _sse("error", {"detail": str(e)})
        except Exception as e:
            log_error(e, context="generate_resume_stream")
            yield _sse("error", {"detail": "Internal server error"})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/pdf")
async def resume_pdf(body: ResumePdfIn):
    """Render resume markdown (e.g. /generate output, possibly user-edited)
    to a downloadable PDF."""
    try:
        pdf_bytes = markdown_to_pdf(body.markdown)
    except Exception as e:
        raise HTTPException(422, f"Could not render PDF: {e}")
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", body.filename or "resume").strip("-") or "resume"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
    )


async def _parse_and_save(user_id: str, raw_text: str) -> ResumeOut:
    result = await parse_graph.ainvoke({"raw_text": raw_text})
    parsed = result["parsed"]
    profile = parsed.model_dump(exclude={"markdown"})
    storage.save_resume(user_id, parsed.markdown, profile)
    return ResumeOut(user_id=user_id, markdown=parsed.markdown, profile=profile)
