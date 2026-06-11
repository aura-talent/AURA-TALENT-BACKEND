from functools import lru_cache

from langchain.chat_models import init_chat_model

from .config import settings


@lru_cache(maxsize=4)
def get_llm(temperature: float = 0.2):
    """Provider-agnostic model factory. API keys come from server env vars
    (ANTHROPIC_API_KEY / OPENAI_API_KEY); users never supply keys."""
    return init_chat_model(settings.model_name, temperature=temperature)
