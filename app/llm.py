from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.callbacks.base import BaseCallbackHandler
from typing import Any, Dict, List

from .config import settings
from .logging_config import logger, log_llm_call


class LoggingCallbackHandler(BaseCallbackHandler):
    """Callback handler to log all LLM interactions"""
    
    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> None:
        """Log when LLM starts"""
        logger.info(f"🤖 LLM START: {settings.model_name}")
        if prompts:
            logger.info(f"Prompt (first 300 chars): {prompts[0][:300]}...")
    
    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """Log when LLM ends"""
        logger.info(f"✅ LLM END: {settings.model_name}")
        try:
            if hasattr(response, 'generations') and response.generations:
                text = response.generations[0][0].text
                logger.info(f"Response (first 300 chars): {text[:300]}...")
        except Exception as e:
            logger.debug(f"Could not log LLM response: {e}")
    
    def on_llm_error(self, error: Exception, **kwargs: Any) -> None:
        """Log when LLM errors"""
        logger.error(f"❌ LLM ERROR: {type(error).__name__}: {str(error)}")


@lru_cache(maxsize=4)
def get_llm(temperature: float = 0.2):
    """Provider-agnostic model factory. Default provider is Google Vertex AI /
    Gemini (free tier) via MODEL_NAME + GOOGLE_APPLICATION_CREDENTIALS; other
    providers (ANTHROPIC_API_KEY / OPENAI_API_KEY) work too by changing
    MODEL_NAME. Users never supply keys — all server env vars.

    timeout/max_retries are set explicitly because every provider client
    defaults to an UNBOUNDED wait (timeout=None) and a generous retry count.
    Nothing downstream imposes its own deadline, so a single stalled request
    would hang its caller indefinitely — and since the scheduler sweep and the
    seeding script both await evaluations one after another, one stuck call
    silently stops everything queued behind it.
    """
    logger.info(
        f"Initializing LLM: {settings.model_name} (temp={temperature}, "
        f"timeout={settings.llm_timeout_seconds}s, retries={settings.llm_max_retries})"
    )
    llm = init_chat_model(
        settings.model_name,
        temperature=temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    """Model factory for Google Vertex AI / Gemini via MODEL_NAME +
    GOOGLE_APPLICATION_CREDENTIALS (or GOOGLE_API_KEY for AI Studio). Only the
    Google provider packages are installed — no other provider is wired up.
    Users never supply keys — all server env vars."""
    logger.info(f"Initializing LLM: {settings.model_name} (temp={temperature})")
    llm = init_chat_model(settings.model_name, temperature=temperature)
    logger.info(f"✅ LLM initialized: {settings.model_name}")
    return llm


def extract_text(message: Any) -> str:
    """Normalize an AIMessage's .content into a plain string.

    Most providers return content as a str, but some (notably Gemini via
    langchain_google_vertexai) return a list of content blocks instead,
    e.g. [{"type": "text", "text": "..."}], especially once thinking/
    citation metadata is present. Downstream Pydantic schemas expect a
    plain str, so collapse block lists into their concatenated text here
    rather than at every call site.
    """
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)
