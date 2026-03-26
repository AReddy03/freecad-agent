"""
LangChain tool definitions — thin wrappers over FreeCADClient.
Call make_freecad_tools(config) to get the list of bound tools.
The rag_search tool is created separately in agent/rag.py.
"""

import base64
from typing import Annotated

from langchain_core.tools import tool

from agent.config import UserConfig
from agent.freecad_client import FreeCADClient, FreeCADConnectionError

# Module-level client; one connection per process.
_client: FreeCADClient | None = None


def _get_client(config: UserConfig) -> FreeCADClient:
    global _client
    if _client is None:
        _client = FreeCADClient(host=config.freecad_host, port=config.freecad_port)
    _client.connect()
    return _client


def make_freecad_tools(config: UserConfig) -> list:
    """Return LangChain tools bound to the given FreeCAD connection config."""

    @tool
    def execute_script(
        code: Annotated[str, "Python code to execute inside FreeCAD"]
    ) -> str:
        """Run Python code inside FreeCAD using its scripting API.
        App, Gui, FreeCAD, and FreeCADGui are available in the namespace.
        Returns stdout. On error, returns a string starting with 'FREECAD ERROR:'."""
        try:
            client = _get_client(config)
            output = client.execute_script(code)
            return output if output else "(script executed with no output)"
        except FreeCADConnectionError as e:
            return f"CONNECTION ERROR: {e}"
        except RuntimeError as e:
            return f"FREECAD ERROR: {e}"

    @tool
    def get_screenshot(
        direction: Annotated[
            str, "View direction: front | back | top | bottom | left | right | iso"
        ] = "iso",
    ) -> str:
        """Capture the current FreeCAD 3D view as a PNG image.
        Returns a base64-encoded PNG string, or an error message."""
        try:
            client = _get_client(config)
            png_bytes = client.get_screenshot(direction)
            return base64.b64encode(png_bytes).decode()
        except FreeCADConnectionError as e:
            return f"CONNECTION ERROR: {e}"
        except RuntimeError as e:
            return f"FREECAD ERROR: {e}"

    @tool
    def list_objects() -> str:
        """List all objects currently in the FreeCAD document.
        Returns a formatted string with each object's name, label, and type.
        Call this before any script to understand what is already in the scene."""
        try:
            client = _get_client(config)
            objects = client.list_objects()
            if not objects:
                return "Document is empty — no objects."
            lines = [f"- {o['name']} ({o['label']}) [{o['type']}]" for o in objects]
            return f"{len(objects)} object(s):\n" + "\n".join(lines)
        except FreeCADConnectionError as e:
            return f"CONNECTION ERROR: {e}"

    @tool
    def clear_document() -> str:
        """Remove ALL objects from the active FreeCAD document.
        *** DESTRUCTIVE — the safety system will ask the user to confirm before this runs. ***"""
        try:
            client = _get_client(config)
            client.clear_document()
            return "Document cleared."
        except FreeCADConnectionError as e:
            return f"CONNECTION ERROR: {e}"

    @tool
    def save_document(
        path: Annotated[
            str,
            "Full file path to save as (e.g. C:/Users/you/model.FCStd). "
            "Leave empty to save in-place (document must already have a filename).",
        ] = "",
    ) -> str:
        """Save the FreeCAD document to disk.
        *** DESTRUCTIVE when saving to an existing path — confirmation required. ***"""
        try:
            client = _get_client(config)
            saved = client.save_document(path)
            return f"Document saved to: {saved}"
        except FreeCADConnectionError as e:
            return f"CONNECTION ERROR: {e}"
        except RuntimeError as e:
            return f"FREECAD ERROR: {e}"

    return [execute_script, get_screenshot, list_objects, clear_document, save_document]
