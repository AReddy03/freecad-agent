"""
User configuration — stored at ~/.freecad-agent/config.json.
Written by the Settings panel in the UI; read by every agent component.

The FREECAD_HOST / FREECAD_PORT environment variables override the saved
connection settings (the Docker image uses them to reach FreeCAD on the host).
"""

import json
import os
from pathlib import Path
from pydantic import BaseModel

CONFIG_PATH = Path.home() / ".freecad-agent" / "config.json"

# Config field -> environment variable that overrides it when set
ENV_OVERRIDES: dict[str, str] = {
    "freecad_host": "FREECAD_HOST",
    "freecad_port": "FREECAD_PORT",
}

# Models available per provider (used to populate the Settings dropdown)
PROVIDER_MODELS: dict[str, list[str]] = {
    "anthropic": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    "openai":    ["gpt-4o", "gpt-4o-mini"],
    "google":    ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"],
    "ollama":    [],  # populated dynamically at runtime via ollama list
}


class UserConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    api_key: str = ""
    # FreeCAD RPC server address (matches rpc_server.py defaults)
    freecad_host: str = "127.0.0.1"
    freecad_port: int = 65432
    # Experimental: inject tutorial RAG context into every reason node call
    use_tutorial_rag: bool = False

    @property
    def needs_api_key(self) -> bool:
        return self.provider != "ollama"

    @property
    def is_ready(self) -> bool:
        """True when the config has enough info to run the agent."""
        if self.needs_api_key and not self.api_key:
            return False
        return bool(self.provider and self.model)


def env_overridden_fields() -> set[str]:
    """Config fields currently overridden by an environment variable."""
    return {field for field, var in ENV_OVERRIDES.items() if os.environ.get(var)}


def _read_saved() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_config() -> UserConfig:
    saved = _read_saved()
    overrides = {field: os.environ[ENV_OVERRIDES[field]] for field in env_overridden_fields()}
    for data in ({**saved, **overrides}, saved):
        try:
            return UserConfig(**data)
        except Exception:
            continue
    return UserConfig()


def save_config(config: UserConfig) -> None:
    data = config.model_dump()
    # Environment overrides are not the user's choice — keep the saved values,
    # so e.g. Docker's host.docker.internal never leaks into a local config.
    saved = _read_saved()
    defaults = UserConfig().model_dump()
    for field in env_overridden_fields():
        data[field] = saved.get(field, defaults[field])
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)
