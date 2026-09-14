"""
LLM factory — returns a LangChain BaseChatModel based on user config.
Swapping providers is a config change; nothing else in the codebase
imports provider-specific classes.
"""

from langchain_core.language_models import BaseChatModel
from agent.config import UserConfig

OLLAMA_URL = "http://localhost:11434"


def get_llm(config: UserConfig) -> BaseChatModel:
    match config.provider:
        case "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=config.model,
                api_key=config.api_key,
                streaming=True,
            )
        case "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=config.model,
                api_key=config.api_key,
                streaming=True,
            )
        case "google":
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=config.model,
                google_api_key=config.api_key,
            )
        case "ollama":
            from langchain_ollama import ChatOllama
            # Ollama runs locally — no API key, no streaming flag needed
            return ChatOllama(model=config.model)
        case _:
            raise ValueError(f"Unknown LLM provider: {config.provider!r}")


def get_ollama_models() -> list[str] | None:
    """
    Return locally pulled Ollama model names, or None if Ollama isn't reachable.
    A single request answers both "is it running?" and "which models?".
    """
    try:
        import requests
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
    except Exception:
        return None
    if resp.status_code != 200:
        return []  # something answered, but it can't list models
    try:
        return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        return []
