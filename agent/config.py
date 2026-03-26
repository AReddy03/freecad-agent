"""
User configuration — stored at ~/.freecad-agent/config.json.
Written by the Settings panel in the UI; read by every agent component.
"""

import json
from pathlib import Path
from pydantic import BaseModel

CONFIG_PATH = Path.home() / ".freecad-agent" / "config.json"

# Models available per provider (used to populate the Settings dropdown)
PROVIDER_MODELS: dict[str, list[str]] = {
    "anthropic": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    "openai":    ["gpt-4o", "gpt-4o-mini"],
    "google":    ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro"],
    "ollama":    [],  # populated dynamically at runtime via ollama list
}


class UserConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    api_key: str = ""
    # FreeCAD RPC server address (matches rpc_server.py defaults)
    freecad_host: str = "127.0.0.1"
    freecad_port: int = 65432

    @property
    def needs_api_key(self) -> bool:
        return self.provider != "ollama"

    @property
    def is_ready(self) -> bool:
        """True when the config has enough info to run the agent."""
        if self.needs_api_key and not self.api_key:
            return False
        return bool(self.provider and self.model)


def load_config() -> UserConfig:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            return UserConfig(**data)
        except Exception:
            pass
    return UserConfig()


def save_config(config: UserConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config.model_dump(), f, indent=2)
