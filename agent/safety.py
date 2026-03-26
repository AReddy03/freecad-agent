"""
Classifies pending tool calls as safe or destructive.
Used by the destructive_check node in the LangGraph graph.
"""

# Tool names that require explicit user confirmation
DESTRUCTIVE_TOOLS = {"clear_document", "save_document"}


def is_destructive(tool_name: str, tool_args: dict) -> bool:
    """Return True if this tool call requires user confirmation before running."""
    if tool_name == "clear_document":
        return True
    if tool_name == "save_document":
        # Saving to a specified path may overwrite an existing file
        return bool(tool_args.get("path", "").strip())
    return False


def confirmation_message(tool_name: str, tool_args: dict) -> str:
    """Return the confirmation prompt to show the user."""
    if tool_name == "clear_document":
        return (
            "**Warning:** This will remove **all objects** from the FreeCAD document. "
            "This cannot be undone.\n\nType **yes** to confirm, or **no** to cancel."
        )
    if tool_name == "save_document":
        path = tool_args.get("path", "")
        return (
            f"**Warning:** This will save the document to `{path}`, "
            "which may overwrite an existing file.\n\n"
            "Type **yes** to confirm, or **no** to cancel."
        )
    return "**Confirm this action?** Type **yes** or **no**."
