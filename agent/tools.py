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


def make_freecad_tools(config: UserConfig, memory_store=None, skills_registry=None) -> list:
    """Return LangChain tools bound to the given FreeCAD connection config.

    Args:
        config:           user's LLM provider / model / API key / FreeCAD connection config
        memory_store:     optional MemoryStore — adds the memory_save tool when provided
        skills_registry:  optional SkillsRegistry — adds the skill_search tool when provided
    """

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

    extra_tools = []

    # -----------------------------------------------------------------------
    # memory_save  (only when memory_store is provided)
    # -----------------------------------------------------------------------
    if memory_store is not None:
        from agent.memory import MemoryType

        @tool
        def memory_save(
            content: Annotated[str, "The information to remember across sessions"],
            memory_type: Annotated[
                str,
                "Category: preference | script_pattern | session_summary | fact",
            ] = "fact",
            importance: Annotated[
                float,
                "Importance from 0.0 to 5.0 (default 1.0). Use 2-3 for frequently useful facts.",
            ] = 1.0,
            tags: Annotated[
                str,
                "Comma-separated tags for later filtering, e.g. 'units,metric' (optional)",
            ] = "",
        ) -> str:
            """Save a piece of information to long-term memory that persists across sessions.
            Use for user preferences (units, naming style, workbench choices), successful
            FreeCAD script patterns, or anything the user explicitly asks to remember.
            This does NOT write to the FreeCAD document."""
            try:
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
                mid = memory_store.save(
                    content=content,
                    memory_type=MemoryType(memory_type),
                    importance=float(importance),
                    tags=tag_list,
                )
                return f"Saved to memory (id={mid}): {content[:80]}"
            except Exception as e:
                return f"MEMORY ERROR: {e}"

        extra_tools.append(memory_save)

    # -----------------------------------------------------------------------
    # skill_search  (only when skills_registry is provided)
    # -----------------------------------------------------------------------
    if skills_registry is not None:

        @tool
        def skill_search(
            query: Annotated[
                str,
                "Describe the CAD operation or design challenge you need guidance on",
            ],
        ) -> str:
            """Search the CAD skills library for best-practice guidance documents.
            Returns the full content of up to 2 matched skills.
            Call this when working on sketches, feature tree organisation, parametric
            modelling, assembly design, manufacturing constraints, or tolerancing."""
            matched = skills_registry.match_skills(query, top_k=2)
            if not matched:
                all_names = ", ".join(skills_registry.skill_names())
                return (
                    f"No skills matched '{query}'. "
                    f"Available skills: {all_names}"
                )
            parts = []
            for skill in matched:
                parts.append(f"### Skill: {skill.name}\n\n{skill.content.strip()}")
            return "\n\n---\n\n".join(parts)

        extra_tools.append(skill_search)

    return [execute_script, get_screenshot, list_objects, clear_document, save_document] + extra_tools
