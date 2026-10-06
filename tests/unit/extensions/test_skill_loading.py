"""Unit tests for workspace skill discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.domain.errors import SkillError
from newbot.domain.skill import Skill
from newbot.extensions.skills import load_skills, render_skill_summary


def _skill(root: Path, name: str, text: str) -> None:
    directory = root / "skills" / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(text, encoding="utf-8")


def test_loads_a_skill_with_its_description_and_body(tmp_path: Path) -> None:
    _skill(tmp_path, "greet", "---\ndescription: Say hello\n---\n\nDo it warmly.\n")

    skills = load_skills(tmp_path)

    assert [skill.name for skill in skills] == ["greet"]
    assert skills[0].description == "Say hello"
    assert skills[0].body == "Do it warmly."


def test_skills_are_ordered_by_directory_name(tmp_path: Path) -> None:
    _skill(tmp_path, "beta", "---\ndescription: b\n---\n\nb")
    _skill(tmp_path, "alpha", "---\ndescription: a\n---\n\na")

    assert [skill.name for skill in load_skills(tmp_path)] == ["alpha", "beta"]


def test_a_missing_skills_directory_loads_nothing(tmp_path: Path) -> None:
    assert load_skills(tmp_path) == ()


def test_a_directory_without_a_skill_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "skills" / "notes").mkdir(parents=True)

    assert load_skills(tmp_path) == ()


def test_unknown_frontmatter_keys_are_ignored(tmp_path: Path) -> None:
    _skill(tmp_path, "greet", "---\ndescription: d\nlicense: MIT\n---\n\nbody\n")

    assert load_skills(tmp_path)[0].description == "d"


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("greet", "Just some text.\n"),
        ("greet", "---\nname: greet\n---\n\nbody\n"),
        ("greet", "---\ndescription: [unclosed\n---\n\nbody\n"),
        ("bad name", "---\ndescription: x\n---\n\nbody\n"),
    ],
    ids=["no-frontmatter", "no-description", "invalid-yaml", "unsafe-name"],
)
def test_a_malformed_skill_is_rejected(tmp_path: Path, name: str, text: str) -> None:
    _skill(tmp_path, name, text)

    with pytest.raises(SkillError):
        load_skills(tmp_path)


def test_the_summary_lists_names_and_is_empty_without_skills() -> None:
    assert render_skill_summary(()) == ""

    summary = render_skill_summary(
        (Skill(name="greet", description="Say hello", body="body"),)
    )

    assert "greet" in summary
    assert "Say hello" in summary
