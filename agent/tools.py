"""
LangChain tool definitions — thin wrappers over FreeCADClient.
Call make_freecad_tools(config) to get the list of bound tools.
The rag_search tool is created separately in agent/rag.py.
"""

import threading
from typing import Annotated, Callable

from langchain_core.tools import tool

from agent.config import UserConfig
from agent.freecad_client import FreeCADClient, FreeCADConnectionError

# One client per FreeCAD address, shared process-wide. FreeCADClient serialises
# requests internally, so it is safe to share across threads.
_clients: dict[tuple[str, int], FreeCADClient] = {}
_clients_lock = threading.Lock()


def get_client(config: UserConfig) -> FreeCADClient:
    """Return the shared client for config's FreeCAD address (connects lazily)."""
    key = (config.freecad_host, config.freecad_port)
    with _clients_lock:
        client = _clients.get(key)
        if client is None:
            client = _clients[key] = FreeCADClient(host=key[0], port=key[1])
    return client


def _error_text(e: Exception) -> str:
    prefix = "CONNECTION ERROR" if isinstance(e, FreeCADConnectionError) else "FREECAD ERROR"
    return f"{prefix}: {e}"


def _guard(action: Callable[[], str]) -> str:
    """Run a FreeCAD call, turning client errors into text the LLM can act on."""
    try:
        return action()
    except (FreeCADConnectionError, RuntimeError) as e:
        return _error_text(e)


def _format_objects(objects: list[dict]) -> str:
    if not objects:
        return "Document is empty — no objects."
    lines = [f"- {o['name']} ({o['label']}) [{o['type']}]" for o in objects]
    return f"{len(objects)} object(s):\n" + "\n".join(lines)


def make_freecad_tools(config: UserConfig) -> list:
    """Return LangChain tools bound to the given FreeCAD connection config."""

    def client() -> FreeCADClient:
        return get_client(config)

    @tool
    def execute_script(
        code: Annotated[str, "Python code to execute inside FreeCAD"]
    ) -> str:
        """Run Python code inside FreeCAD using its scripting API.
        App, Gui, FreeCAD, and FreeCADGui are available in the namespace.
        Returns stdout. On error, returns a string starting with 'FREECAD ERROR:'."""
        return _guard(lambda: client().execute_script(code) or "(script executed with no output)")

    @tool(response_format="content_and_artifact")
    def get_screenshot(
        direction: Annotated[
            str, "View direction: front | back | top | bottom | left | right | iso"
        ] = "iso",
    ) -> tuple[str, str | None]:
        """Capture the current FreeCAD 3D view and show it to the user.
        Returns a short confirmation (the image goes to the UI, not to you),
        or an error message."""
        # The base64 PNG travels as the ToolMessage artifact: it reaches the UI
        # via state["last_screenshot"] but is never sent back to the LLM.
        try:
            image_b64 = client().get_screenshot_base64(direction)
        except (FreeCADConnectionError, RuntimeError) as e:
            return _error_text(e), None
        return f"Screenshot captured ({direction} view) and shown to the user.", image_b64

    @tool
    def list_objects() -> str:
        """List all objects in the FreeCAD document, read live from FreeCAD,
        with each object's name, label, and type.
        Call this before writing a script, and before any operation that references
        existing geometry (fillet, chamfer, boolean, pocket, mirror, or any object
        you did not create in the current turn)."""
        return _guard(lambda: _format_objects(client().list_objects()))

    @tool
    def clear_document() -> str:
        """Remove ALL objects from the active FreeCAD document.
        *** DESTRUCTIVE — the safety system will ask the user to confirm before this runs. ***"""
        def clear() -> str:
            client().clear_document()
            return "Document cleared."
        return _guard(clear)

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
        return _guard(lambda: f"Document saved to: {client().save_document(path)}")

    return [execute_script, get_screenshot, list_objects, clear_document, save_document]
