"""
LLM factory — returns a LangChain BaseChatModel based on user config.
Swapping providers is a config change; nothing else in the codebase
imports provider-specific classes.
"""

from langchain_core.language_models import BaseChatModel
from agent.config import UserConfig


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
        case "ollama":
            from langchain_ollama import ChatOllama
            # Ollama runs locally — no API key, no streaming flag needed
            return ChatOllama(model=config.model)
        case _:
            raise ValueError(f"Unknown LLM provider: {config.provider!r}")


def list_ollama_models() -> list[str]:
    """Return locally available Ollama model names, or [] if Ollama is not running."""
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        pass
    return []


def is_ollama_running() -> bool:
    return bool(list_ollama_models()) or _ollama_ping()


def _ollama_ping() -> bool:
    try:
        import requests
        resp = requests.get("http://localhost:11434/", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False
