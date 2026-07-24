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
    MODEL_NAME. Users never supply keys — all server env vars."""
    logger.info(f"Initializing LLM: {settings.model_name} (temp={temperature})")
    llm = init_chat_model(settings.model_name, temperature=temperature)
    logger.info(f"✅ LLM initialized: {settings.model_name}")
    return llm
