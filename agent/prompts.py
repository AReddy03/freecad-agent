SYSTEM_PROMPT = """You are an expert FreeCAD CAD engineer with direct access to a running FreeCAD \
instance via tools. Your job is to fulfil the user's CAD requests by taking action — not just giving advice.

## Rules

1. **Inspect before acting.** Call `list_objects` before writing any script so you know what \
is already in the scene. Never assume names or assume the document is empty.

2. **Consult docs for unfamiliar APIs.** Call `rag_search` before writing a script if you are \
not certain of the correct FreeCAD Python API (e.g. workbench-specific operations, constraints, \
assemblies). Skip rag_search for basic primitives you know well (Box, Cylinder, Sphere, boolean ops).

3. **Verify every change visually.** After every `execute_script` that modifies geometry, call \
`get_screenshot("iso")` and show the result to the user. Do not report success without a screenshot.

4. **Self-correct errors.** If `execute_script` returns a string starting with "FREECAD ERROR:", \
analyse the traceback, fix the script, and retry. You get up to 3 attempts before giving up and \
reporting the problem to the user.

5. **Never bypass the safety system.** You must not call `clear_document` or `save_document` to \
a path without user confirmation. The graph handles this automatically — do not add your own \
confirmation prompts.

6. **Be concise.** Don't narrate what you're about to do. Just do it and report the outcome with \
the screenshot. One or two sentences is enough.

7. **Check the document state before referencing existing geometry.** Before any operation that \
references existing objects (fillet, chamfer, boolean, pocket, mirror, array), check the \
"Current document state" section below. If you are unsure what exists, call \
`get_feature_tree()` to get the live state from FreeCAD before proceeding.

8. **Set descriptive labels.** When creating objects, set their Label to something meaningful \
(e.g. "base_flange", "center_hole"). Do not rely on FreeCAD's default names like "Box" or "Sketch001".

## FreeCAD scripting conventions

- Always call `App.ActiveDocument.recompute()` after adding or modifying objects.
- Use `App.ActiveDocument.addObject(type, name)` to create objects.
- Object names are auto-assigned. Use the names returned by `list_objects`.
- Import workbench modules at the top of every script: `import Part`, `import Draft`, etc.
- `App` and `Gui` are available as aliases for `FreeCAD` and `FreeCADGui`.
- To get an object: `obj = App.ActiveDocument.getObject("Name")`.
"""

_MAX_CHARS = 3200        # ~800 tokens at 4 chars/token
_MAX_ENTRIES = 30
_MAX_TUTORIAL_CHARS = 900   # 3 chunks × ~300 chars each — injected every turn, keep tight
_MAX_MEMORY_CHARS = 1200    # ~300 tokens; preferences + recent summaries
_MAX_SKILLS_CHARS = 2000    # matched skill body — up to 2 skills × ~1000 chars each
_MAX_SKILLS_INDEX_CHARS = 600  # brief skills listing in system prompt
_MAX_ALL_SKILLS_CHARS = 20000  # all skills injected every turn; ~5 000 tokens — fine for 100k+ context models
_MAX_SKILL_BODY_CHARS = 3500   # per-skill cap so no single skill dominates


def format_memory_context(memory_store, query: str = "") -> str:
    """
    Build the memory section for the system prompt.
    Called every turn from the reason node — no LLM calls, pure SQL.

    Sections (each omitted when empty):
      ## Long-term memory
      ### User preferences       — all PREFERENCE memories, high-importance first
      ### Past sessions          — 3 most recent SESSION_SUMMARY memories
      ### Relevant memories      — FTS5 search results for current query
    """
    from agent.memory import MemoryType  # local import avoids circular at module level

    lines = []

    # --- Preferences (always shown) ---
    try:
        prefs = memory_store.get_all_preferences()
    except Exception:
        prefs = []

    pref_lines = []
    for p in prefs[:10]:
        pref_lines.append(f"- {p['content']}")

    # --- Session summaries ---
    try:
        summaries = memory_store.get_session_summaries(limit=3)
    except Exception:
        summaries = []

    summary_lines = []
    for s in summaries:
        date = s["created_at"][:10]
        summary_lines.append(f"- [{date}] {s['content'][:120]}")

    # --- Relevant to current query (FTS5) ---
    relevant_lines = []
    shown_ids = {p["id"] for p in prefs} | {s["id"] for s in summaries}
    if query.strip():
        try:
            relevant = memory_store.search(query, memory_type=None, limit=5)
            for r in relevant:
                if r["id"] not in shown_ids:
                    relevant_lines.append(f"- [{r['memory_type']}] {r['content'][:150]}")
        except Exception:
            pass

    if not pref_lines and not summary_lines and not relevant_lines:
        return ""

    lines.append("## Long-term memory")
    if pref_lines:
        lines.append("### User preferences")
        lines.extend(pref_lines)
    if summary_lines:
        lines.append("### Past sessions")
        lines.extend(summary_lines)
    if relevant_lines:
        lines.append("### Relevant memories")
        lines.extend(relevant_lines)

    result = "\n".join(lines)
    if len(result) > _MAX_MEMORY_CHARS:
        result = result[:_MAX_MEMORY_CHARS] + "\n[... memory truncated ...]"
    return result


def format_skills_index(skills_registry) -> str:
    """
    Build a brief skills index for the system prompt — just names and one-liner descriptions.
    Always injected so the agent knows what skills are available.
    The agent can call `skill_search` to retrieve full skill content on demand.
    """
    skills = skills_registry.list_all()
    if not skills:
        return ""

    lines = ["## Available CAD skills (call skill_search to get full guidance)"]
    for s in skills[:20]:
        # Truncate description to first sentence
        first_sentence = s["description"].split(".")[0].strip()
        lines.append(f"- `{s['name']}`: {first_sentence[:100]}")

    result = "\n".join(lines)
    if len(result) > _MAX_SKILLS_INDEX_CHARS:
        result = result[:_MAX_SKILLS_INDEX_CHARS] + "\n[... more skills available ...]"
    return result


def format_matched_skills_context(skills: list) -> str:
    """
    Format the content of skills that matched the current query.
    Injects up to 2 matched skills, capped at _MAX_SKILLS_CHARS total.
    Each skill: header + full markdown content.
    """
    if not skills:
        return ""

    lines = ["## Relevant CAD design guidance (from skills library)"]
    remaining = _MAX_SKILLS_CHARS - len(lines[0])

    for skill in skills[:2]:
        header = f"\n### Skill: {skill.name}"
        body = skill.content.strip()
        chunk = header + "\n" + body
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            chunk = chunk[:remaining] + "\n[... truncated ...]"
        lines.append(chunk)
        remaining -= len(chunk)

    if len(lines) == 1:
        return ""

    return "\n".join(lines)


def format_all_skills_context(skills_registry) -> str:
    """
    Inject the full content of ALL loaded skills into the system prompt.
    Called unconditionally every turn so the agent always has complete
    CAD best-practice guidance — no keyword matching required.

    Each skill is capped at _MAX_SKILL_BODY_CHARS; total capped at
    _MAX_ALL_SKILLS_CHARS.  Returns "" if no skills are loaded.
    """
    all_skills = skills_registry.skill_names()
    if not all_skills:
        return ""

    sections = ["## CAD Design Skills — Best Practices"]
    total = len(sections[0])

    for name in all_skills:
        skill = skills_registry.get_skill(name)
        if skill is None:
            continue
        body = skill.content.strip()
        if len(body) > _MAX_SKILL_BODY_CHARS:
            body = body[:_MAX_SKILL_BODY_CHARS] + "\n[... truncated — call skill_search for full content ...]"
        block = f"\n### {skill.name}\n{body}"
        if total + len(block) > _MAX_ALL_SKILLS_CHARS:
            sections.append(
                f"\n[... remaining skills omitted — call skill_search('{name}') to retrieve ...]"
            )
            break
        sections.append(block)
        total += len(block)

    if len(sections) == 1:
        return ""
    return "\n".join(sections)


def format_tutorial_context(docs: list) -> str:
    """
    Format retrieved tutorial chunks for injection into the system prompt.
    Each doc is a LangChain Document with .page_content and .metadata.
    Capped at _MAX_TUTORIAL_CHARS to stay within per-turn token budget.
    Returns an empty string if docs is empty.
    """
    if not docs:
        return ""

    lines = ["## Relevant design guidance"]
    for i, doc in enumerate(docs, 1):
        title = doc.metadata.get("title", "")
        source = doc.metadata.get("source", "")
        header = f"[{i}] {title}" if title else f"[{i}] {source}"
        lines.append(header)
        lines.append(doc.page_content.strip())

    result = "\n\n".join(lines)
    if len(result) > _MAX_TUTORIAL_CHARS:
        result = result[:_MAX_TUTORIAL_CHARS] + "\n[... truncated ...]"
    return result


def format_feature_tree_context(feature_tree: list[dict]) -> str:
    """
    Format the feature tree log for injection into the system prompt.
    Truncates to the most recent _MAX_ENTRIES entries and caps at _MAX_CHARS.
    """
    if not feature_tree:
        return (
            "## Current document state\n"
            "No objects created yet. This is a fresh FreeCAD document."
        )

    valid = [e for e in feature_tree if e.get("valid", True)]
    entries = valid[-_MAX_ENTRIES:]
    omitted = len(valid) - len(entries)

    lines = [f"## Current document state ({len(valid)} object(s) in document)"]
    if omitted:
        lines.append(f"[... {omitted} earlier feature(s) omitted for brevity ...]")

    for e in entries:
        turn = f"T{e.get('turn_index', '?')}"
        name = e.get("name", "?")
        type_id = e.get("type_id", "?")
        label = e.get("label", name)
        summary = e.get("operation_summary", "")
        lines.append(f"{turn} | {label} ({name}) [{type_id}] — {summary}")

    result = "\n".join(lines)
    if len(result) > _MAX_CHARS:
        result = result[:_MAX_CHARS] + "\n[... truncated ...]"
    return result
