"""
Unit tests for agent/skills.py — no FreeCAD required.
"""

from pathlib import Path

import pytest

from agent.skills import Skill, SkillsRegistry, _parse_skill_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_skill(tmp_path: Path, name: str, description: str, content: str) -> Path:
    """Write a SKILL.md file into a subdirectory of tmp_path."""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    # Build frontmatter explicitly to avoid textwrap.dedent breaking on content
    # that contains lines with no indentation.
    text = f"---\nname: {name}\ndescription: >\n  {description}\n---\n\n{content}\n"
    skill_file.write_text(text, encoding="utf-8")
    return skill_file


# ---------------------------------------------------------------------------
# _parse_skill_file
# ---------------------------------------------------------------------------

def test_parse_skill_file_basic(tmp_path):
    path = write_skill(
        tmp_path,
        "test-skill",
        "A test skill for unit testing.",
        "# Test\n\nThis is the body.",
    )
    skill = _parse_skill_file(path)
    assert skill is not None
    assert skill.name == "test-skill"
    assert "test skill" in skill.description.lower()
    assert "This is the body" in skill.content


def test_parse_skill_file_missing_file(tmp_path):
    skill = _parse_skill_file(tmp_path / "nonexistent" / "SKILL.md")
    assert skill is None


def test_parse_skill_file_no_frontmatter(tmp_path):
    bad_file = tmp_path / "bad.md"
    bad_file.write_text("# No frontmatter here\n", encoding="utf-8")
    skill = _parse_skill_file(bad_file)
    assert skill is None


def test_parse_skill_file_falls_back_to_dirname(tmp_path):
    """If name is missing from frontmatter, use the parent directory name."""
    skill_dir = tmp_path / "my-skill-name"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\ndescription: some description\n---\nBody text.\n",
        encoding="utf-8",
    )
    skill = _parse_skill_file(skill_file)
    assert skill is not None
    assert skill.name == "my-skill-name"


# ---------------------------------------------------------------------------
# SkillsRegistry loading
# ---------------------------------------------------------------------------

def test_registry_loads_skills(tmp_path):
    write_skill(tmp_path, "skill-a", "Does thing A.", "Body A")
    write_skill(tmp_path, "skill-b", "Does thing B.", "Body B")
    registry = SkillsRegistry(skills_dir=tmp_path)
    assert registry.count() == 2


def test_registry_empty_dir(tmp_path):
    registry = SkillsRegistry(skills_dir=tmp_path)
    assert registry.count() == 0


def test_registry_nonexistent_dir(tmp_path):
    registry = SkillsRegistry(skills_dir=tmp_path / "does-not-exist")
    assert registry.count() == 0


def test_registry_loads_real_skills():
    """The built-in skills/ directory should load 6 skills."""
    registry = SkillsRegistry()
    assert registry.count() >= 6, f"Expected >=6 skills, got {registry.count()}"


# ---------------------------------------------------------------------------
# list_all / get_skill
# ---------------------------------------------------------------------------

def test_list_all_returns_metadata_only(tmp_path):
    write_skill(tmp_path, "my-skill", "Trigger: create sketch.", "Long body content...")
    registry = SkillsRegistry(skills_dir=tmp_path)
    skills = registry.list_all()
    assert len(skills) == 1
    assert "name" in skills[0]
    assert "description" in skills[0]
    assert "content" not in skills[0]  # content not in metadata list


def test_get_skill_returns_full_content(tmp_path):
    write_skill(tmp_path, "full-skill", "Full skill.", "# Full body\n\nLots of content.")
    registry = SkillsRegistry(skills_dir=tmp_path)
    skill = registry.get_skill("full-skill")
    assert skill is not None
    assert isinstance(skill, Skill)
    assert "Full body" in skill.content


def test_get_skill_unknown_returns_none(tmp_path):
    registry = SkillsRegistry(skills_dir=tmp_path)
    assert registry.get_skill("nonexistent") is None


# ---------------------------------------------------------------------------
# match_skills
# ---------------------------------------------------------------------------

def test_match_skills_finds_relevant(tmp_path):
    write_skill(tmp_path, "sketch-skill", "Use this for sketches, constraints, 2D profiles.", "Body")
    write_skill(tmp_path, "assembly-skill", "Use this for assembly design and mates.", "Body")
    registry = SkillsRegistry(skills_dir=tmp_path)

    matched = registry.match_skills("create a sketch profile for a bracket")
    assert len(matched) >= 1
    assert matched[0].name == "sketch-skill"


def test_match_skills_returns_empty_for_no_match(tmp_path):
    write_skill(tmp_path, "some-skill", "Very specific trigger keyword zxqwerty.", "Body")
    registry = SkillsRegistry(skills_dir=tmp_path)

    matched = registry.match_skills("unrelated query about chocolate cake")
    assert len(matched) == 0


def test_match_skills_top_k_limit(tmp_path):
    for i in range(5):
        write_skill(tmp_path, f"skill-{i}", f"Use for extrude revolve loft sweep operation {i}.", "Body")
    registry = SkillsRegistry(skills_dir=tmp_path)

    matched = registry.match_skills("extrude revolve loft operation", top_k=2)
    assert len(matched) <= 2


def test_match_skills_empty_query(tmp_path):
    write_skill(tmp_path, "any-skill", "Trigger on anything.", "Body")
    registry = SkillsRegistry(skills_dir=tmp_path)
    assert registry.match_skills("") == []


# ---------------------------------------------------------------------------
# skill_names / count
# ---------------------------------------------------------------------------

def test_skill_names(tmp_path):
    write_skill(tmp_path, "alpha", "Alpha skill.", "")
    write_skill(tmp_path, "beta", "Beta skill.", "")
    registry = SkillsRegistry(skills_dir=tmp_path)
    names = registry.skill_names()
    assert "alpha" in names
    assert "beta" in names


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

def test_singleton_returns_same_instance():
    import agent.skills as skills_module
    skills_module._registry = None
    r1 = skills_module.get_skills_registry()
    r2 = skills_module.get_skills_registry()
    assert r1 is r2
    skills_module._registry = None  # clean up


# ---------------------------------------------------------------------------
# Real skills — smoke tests
# ---------------------------------------------------------------------------

def test_real_sketching_skill_matches():
    registry = SkillsRegistry()
    matched = registry.match_skills("create a sketch for a mounting bracket with constraints")
    names = [s.name for s in matched]
    assert "sketching-and-constraints" in names


def test_real_parametric_skill_matches():
    registry = SkillsRegistry()
    matched = registry.match_skills("extrude a pad and add a pocket cut parametric model")
    names = [s.name for s in matched]
    assert "parametric-modeling" in names


def test_real_assembly_skill_matches():
    registry = SkillsRegistry()
    matched = registry.match_skills("assemble two parts with mates in an assembly")
    names = [s.name for s in matched]
    assert "assembly-design" in names
