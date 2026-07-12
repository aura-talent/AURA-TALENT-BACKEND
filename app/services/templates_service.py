from app.storage import get_template_by_id
import json
from datetime import date
from typing import Optional, Dict
from pydantic import BaseModel, Field

from ..llm import get_llm
from ..logging_config import logger
from .. import storage
from ..employer import storage as employer_storage

class DraftResponse(BaseModel):
    subject: str = Field(description="The finalized email or message subject line")
    body: str = Field(description="The finalized email or message body text. High quality, well formatted, single spacing with line breaks.")

class PlaceholderResponse(BaseModel):
    populated: Dict[str, str] = Field(description="A key-value map of placeholder names to their auto-populated text values")

# ── AI Generation Service ─────────────────────────────────────────

async def generate_template_draft(
    prompt: str,
    template_id: Optional[str],
    role: str,
    tone: Optional[str],
    length: Optional[str],
    language: Optional[str],
    placeholders: Optional[dict]
) -> DraftResponse:
    logger.info(f"[templates] Generating template draft. ID: {template_id}, Role: {role}, Tone: {tone}, Language: {language}")
    
    # 1. Look up base template if provided
    base_template = None
    if template_id:
        base_template = get_template_by_id(template_id)
    
    # 2. Build template reference text
    template_ref = ""
    if base_template:
        template_ref = (
            f"Base Template Subject: {base_template['subject_template']}\n"
            f"Base Template Body:\n{base_template['body_template']}\n\n"
        )
    
    # 3. Format pre-filled placeholders if any
    placeholders_str = ""
    if placeholders:
        placeholders_str = "Pre-filled placeholder values:\n" + "\n".join(
            f"[{k}]: {v}" for k, v in placeholders.items() if v
        ) + "\n\n"

    # 4. Construct prompt
    system_prompt = (
        "You are AURA, an expert professional communication assistant. "
        "Your task is to write or edit a high-quality email or message based on the user's instructions.\n\n"
        "Follow these styling rules:\n"
        "1. Write clear, polished, and natural text appropriate for the specified tone.\n"
        "2. Do NOT use markdown bold/italic inside the subject line or email body unless it is helpful for structure. Keep it looking like a standard email.\n"
        "3. Output a direct subject line and body without surrounding conversational filler (like 'Here is your draft:').\n"
        "4. Do NOT leave unresolved bracketed placeholders in the final text (e.g. '[Candidate Name]') unless they were not provided in the pre-filled values. Try to resolve them or make the text flow naturally.\n"
    )
    
    human_prompt = (
        f"{template_ref}"
        f"{placeholders_str}"
        f"User Instruction / Situation: {prompt}\n"
        f"Role context: {role}\n"
        f"Required Tone: {tone or 'Professional'}\n"
        f"Required Length: {length or 'Medium'} (Shorter means concise and direct, Medium is standard, Longer means detailed and comprehensive)\n"
        f"Target Language: {language or 'English'}\n\n"
        "Generate the subject and body in the specified language."
    )
    
    llm = get_llm().with_structured_output(DraftResponse)
    response = await llm.ainvoke([
        ("system", system_prompt),
        ("human", human_prompt)
    ])
    
    return response

# ── Auto-Population Service ───────────────────────────────────────

async def auto_populate_placeholders(
    placeholders: list[str],
    role: str,
    candidate_user_id: Optional[str],
    job_id: Optional[str]
) -> Dict[str, str]:
    logger.info(f"[templates] Auto-populating placeholders: {placeholders} for role: {role}")
    
    # 1. Gather all raw DB details we can find
    candidate_info = {}
    job_info = {}
    employer_info = {}
    
    if candidate_user_id:
        # Fetch resume profile
        resume = storage.get_resume(candidate_user_id)
        if resume:
            profile = resume.get("profile") or {}
            candidate_info["resume_profile"] = profile
            candidate_info["markdown"] = resume.get("markdown", "")
        # Fetch user profile
        user_row = storage.get_user_profile(candidate_user_id)
        if user_row:
            candidate_info["email"] = user_row.get("email")
            candidate_info["full_name"] = user_row.get("full_name") or user_row.get("email", "").split("@")[0]
            
    if job_id:
        job = employer_storage.get_job(job_id)
        if job:
            job_info["title"] = job.get("title")
            job_info["company"] = job.get("company")
            job_info["description"] = job.get("description", "")
            employer_id = job.get("employer_id")
            if employer_id:
                emp_profile = employer_storage.get_employer_profile(employer_id)
                if emp_profile:
                    employer_info["company_name"] = emp_profile.get("company_name")
                    employer_info["hiring_manager"] = emp_profile.get("full_name")

    # If job info doesn't have company but employer info has, copy it
    if not job_info.get("company") and employer_info.get("company_name"):
        job_info["company"] = employer_info["company_name"]
        
    # Standard date resolver
    today_str = date.today().strftime("%B %d, %Y")

    # 2. Build the context prompt for LLM to map placeholders
    context_data = {
        "candidate": {
            "name": candidate_info.get("full_name"),
            "email": candidate_info.get("email"),
            "skills": candidate_info.get("resume_profile", {}).get("skills", []),
            "headline": candidate_info.get("resume_profile", {}).get("headline"),
            "experience": candidate_info.get("resume_profile", {}).get("work_experience_summary")
        },
        "job": {
            "title": job_info.get("title"),
            "company": job_info.get("company") or "Northstar Labs",
            "hiring_manager": employer_info.get("hiring_manager") or "Hiring Manager"
        },
        "current_date": today_str
    }
    
    # 3. Call LLM to intelligently extract and format the placeholders
    system_prompt = (
        "You are AURA, an AI helper. Your job is to extract values for specific email placeholders "
        "from the provided Candidate and Job context. Be precise. If a field is not findable, supply "
        "a logical suggestion based on the context, or fallback to the current date for date fields.\n\n"
        "Provide your answer as a JSON key-value map of placeholder names to their resolved text values."
    )
    
    human_prompt = (
        f"Placeholders to resolve: {placeholders}\n\n"
        f"Context:\n"
        f"{json.dumps(context_data, indent=2)}\n\n"
        f"Candidate Resume Summary (if available):\n"
        f"{candidate_info.get('markdown', '')[:1200]}\n\n"
        "Fill the placeholders. For example, '[Candidate Name]' should map to the candidate's actual name."
    )
    
    try:
        llm = get_llm().with_structured_output(PlaceholderResponse)
        response = await llm.ainvoke([
            ("system", system_prompt),
            ("human", human_prompt)
        ])
        return response.populated
    except Exception as e:
        logger.error(f"Error auto-populating placeholders: {e}")
        # Fallback to crude parsing in case LLM fails
        populated = {}
        for placeholder in placeholders:
            clean_name = placeholder.lower().replace("[", "").replace("]", "").replace(" ", "_")
            if "candidate_name" in clean_name or "name" in clean_name and role == "candidate":
                populated[placeholder] = candidate_info.get("full_name") or "[Candidate Name]"
            elif "company" in clean_name:
                populated[placeholder] = job_info.get("company") or "Northstar Labs"
            elif "position" in clean_name or "role" in clean_name:
                populated[placeholder] = job_info.get("title") or "[Position]"
            elif "manager" in clean_name:
                populated[placeholder] = employer_info.get("hiring_manager") or "Hiring Manager"
            elif "date" in clean_name:
                populated[placeholder] = today_str
            else:
                populated[placeholder] = f"[{placeholder}]"
        return populated
