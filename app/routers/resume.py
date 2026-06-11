import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .. import storage
from ..graphs.resume import extract_text, parse_graph, suggest_graph
from ..schemas import ResumeOut, ResumeTextIn, SuggestIn, SuggestOut
from ..services.jd_fetch import JDFetchError

_SUGGEST_NODE_LABELS = {
    "fetch_jd": "Fetching job description...",
    "suggest": "Generating tailored suggestions...",
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
            yield _sse("error", {"detail": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _parse_and_save(user_id: str, raw_text: str) -> ResumeOut:
    result = await parse_graph.ainvoke({"raw_text": raw_text})
    parsed = result["parsed"]
    profile = parsed.model_dump(exclude={"markdown"})
    storage.save_resume(user_id, parsed.markdown, profile)
    return ResumeOut(user_id=user_id, markdown=parsed.markdown, profile=profile)
