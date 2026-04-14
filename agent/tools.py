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


def make_freecad_tools(config: UserConfig, memory_store=None, skills_registry=None) -> list:
    """Return LangChain tools bound to the given FreeCAD connection config.

    Args:
        config:           user's LLM provider / model / API key / FreeCAD connection config
        memory_store:     optional MemoryStore — adds the memory_save tool when provided
        skills_registry:  optional SkillsRegistry — adds the skill_search tool when provided
    """

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
    def get_feature_tree() -> str:
        """Return the current FreeCAD document object tree as a structured list.
        Reads live state directly from FreeCAD — use this before any operation
        that references existing geometry (fillet, chamfer, boolean, pocket,
        mirror, or any face/edge/body you did not create in the current turn)."""
        try:
            client = _get_client(config)
            objects = client.list_objects()
            if not objects:
                return "Current document is empty — no objects exist."
            lines = ["Current FreeCAD document objects:"]
            for i, o in enumerate(objects, 1):
                lines.append(f"  {i}. {o['name']} ({o['label']}) [{o['type']}]")
            return "\n".join(lines)
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

    return [execute_script, get_screenshot, list_objects, get_feature_tree,
            clear_document, save_document] + extra_tools
