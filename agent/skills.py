"""
Skills registry for the FreeCAD agent.

Skills are knowledge/guidance documents (SKILL.md files with YAML frontmatter)
that encode CAD best practices. The registry loads them from the skills/ directory,
matches them to the current user request via keyword matching, and returns their
content for injection into the system prompt.

Usage:
    from agent.skills import get_skills_registry

    registry = get_skills_registry()
    matched = registry.match_skills("create a sketch for a bracket", top_k=2)
    for skill in matched:
        print(skill.name, skill.content[:200])
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# Frontmatter delimiter
_FM_DELIMITER = "---"


# ---------------------------------------------------------------------------
# Skill dataclass
# ---------------------------------------------------------------------------

@dataclass
class Skill:
    name: str
    description: str   # from YAML frontmatter — contains trigger keywords
    content: str       # full markdown body (without frontmatter)
    path: Path


# ---------------------------------------------------------------------------
# YAML frontmatter parser (no external deps)
# ---------------------------------------------------------------------------

def _parse_skill_file(path: Path) -> Optional[Skill]:
    """
    Parse a SKILL.md file.  Extracts 'name' and 'description' from YAML
    frontmatter and the remaining text as content.
    Returns None if the file cannot be parsed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    # Must start with ---
    if not text.startswith(_FM_DELIMITER):
        return None

    # Find closing ---
    end = text.find(_FM_DELIMITER, len(_FM_DELIMITER))
    if end == -1:
        return None

    frontmatter_raw = text[len(_FM_DELIMITER):end].strip()
    content = text[end + len(_FM_DELIMITER):].strip()

    # Manual parse of the two keys we care about (name + description).
    # Handles multi-line block scalars (description: >\n  ...\n  ...)
    name = ""
    description = ""

    # Split into lines and walk them
    lines = frontmatter_raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        key_match = re.match(r'^(\w[\w-]*):\s*(.*)', line)
        if key_match:
            key = key_match.group(1)
            val = key_match.group(2).strip()

            if val in (">", "|"):
                # Block scalar — collect indented continuation lines
                block_lines = []
                i += 1
                while i < len(lines) and (lines[i].startswith("  ") or lines[i].strip() == ""):
                    block_lines.append(lines[i].strip())
                    i += 1
                val = " ".join(bl for bl in block_lines if bl)
                if key == "name":
                    name = val
                elif key == "description":
                    description = val
                continue  # i already advanced
            else:
                if key == "name":
                    name = val.strip("'\"")
                elif key == "description":
                    description = val.strip("'\"")
        i += 1

    if not name:
        # Fall back to directory name
        name = path.parent.name

    return Skill(name=name, description=description, content=content, path=path)


# ---------------------------------------------------------------------------
# SkillsRegistry
# ---------------------------------------------------------------------------

class SkillsRegistry:
    """
    Loads SKILL.md files from a skills directory and provides:
    - list_all()          — all skills metadata (no content)
    - match_skills()      — keyword-matched skills for a given query
    - get_skill()         — full skill by name
    """

    def __init__(self, skills_dir: Path = _SKILLS_DIR):
        self._skills: dict[str, Skill] = {}
        self._load(skills_dir)

    # -----------------------------------------------------------------------
    # Loading
    # -----------------------------------------------------------------------

    def _load(self, skills_dir: Path) -> None:
        """Recursively scan skills_dir for SKILL.md files."""
        if not skills_dir.exists():
            return
        for skill_file in sorted(skills_dir.rglob("SKILL.md")):
            skill = _parse_skill_file(skill_file)
            if skill and skill.name:
                self._skills[skill.name] = skill

    # -----------------------------------------------------------------------
    # Discovery
    # -----------------------------------------------------------------------

    def list_all(self) -> list[dict]:
        """Return metadata for all loaded skills (no content body)."""
        return [
            {"name": s.name, "description": s.description}
            for s in self._skills.values()
        ]

    def get_skill(self, name: str) -> Optional[Skill]:
        """Return a Skill by exact name, or None if not found."""
        return self._skills.get(name)

    def match_skills(self, query: str, top_k: int = 2) -> list[Skill]:
        """
        Score each skill's description against the query using keyword overlap.
        Returns the top_k skills with the highest score (>0).

        Scoring:
          - Split description into words
          - Count how many query words (>3 chars) appear in the description (case-insensitive)
          - Skills with zero overlap are excluded
        """
        if not query.strip() or not self._skills:
            return []

        query_words = set(
            w.lower() for w in re.split(r'\W+', query) if len(w) > 3
        )
        if not query_words:
            return []

        scores: list[tuple[int, Skill]] = []
        for skill in self._skills.values():
            desc_lower = skill.description.lower()
            score = sum(1 for w in query_words if w in desc_lower)
            if score > 0:
                scores.append((score, skill))

        scores.sort(key=lambda x: -x[0])
        return [skill for _, skill in scores[:top_k]]

    def count(self) -> int:
        return len(self._skills)

    def skill_names(self) -> list[str]:
        return list(self._skills.keys())


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------

_registry: Optional[SkillsRegistry] = None


def get_skills_registry(skills_dir: Path = _SKILLS_DIR) -> SkillsRegistry:
    """Return a module-level singleton SkillsRegistry."""
    global _registry
    if _registry is None:
        _registry = SkillsRegistry(skills_dir)
    return _registry
