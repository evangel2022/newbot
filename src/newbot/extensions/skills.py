"""Load workspace skills: markdown know-how with YAML frontmatter."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from newbot.domain.errors import SkillError
from newbot.domain.skill import Skill

SKILLS_DIRNAME = "skills"
SKILL_FILENAME = "SKILL.md"
_SKILL_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL)
_SUMMARY_HEADER = (
    "Available skills (call the `skill` tool with action=\"read\" before "
    "following one):"
)


class _Frontmatter(BaseModel):
    """The frontmatter fields newbot reads; other keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    description: str = Field(min_length=1)


def load_skills(root: Path) -> tuple[Skill, ...]:
    """Load every ``<root>/skills/<name>/SKILL.md``, ordered by name.

    A directory without ``SKILL.md`` is not a skill and is ignored. A skill
    that exists but is malformed -- an unsafe name, bad YAML, or no
    description -- is a loud ``SkillError``: the operator wrote it
    deliberately, so a typo should fail startup rather than silently vanish
    from the agent's summary.
    """
    directory = root / SKILLS_DIRNAME
    if not directory.is_dir():
        return ()
    skills: list[Skill] = []
    for child in sorted(directory.iterdir()):
        if not child.is_dir():
            continue
        path = child / SKILL_FILENAME
        if not path.is_file():
            continue
        skills.append(_load(child.name, path))
    return tuple(skills)


def render_skill_summary(skills: Sequence[Skill]) -> str:
    """Render the compact catalog that is injected into the system prompt."""
    if not skills:
        return ""
    lines = [_SUMMARY_HEADER]
    lines.extend(f"- {skill.name}: {skill.description}" for skill in skills)
    return "\n".join(lines)


def _load(name: str, path: Path) -> Skill:
    if _SKILL_NAME.fullmatch(name) is None:
        raise SkillError(
            f"{path}: skill directory {name!r} must use letters, digits, "
            "'.', '_' or '-'"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SkillError(f"{path}: could not read skill: {exc}") from exc
    match = _FRONTMATTER.match(text)
    if match is None:
        raise SkillError(f"{path}: skill needs YAML frontmatter delimited by '---'")
    return Skill(
        name=name,
        description=_description(path, match.group(1)),
        body=match.group(2).strip(),
    )


def _description(path: Path, raw: str) -> str:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise SkillError(f"{path}: invalid YAML frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise SkillError(f"{path}: frontmatter must be a mapping")
    try:
        front = _Frontmatter.model_validate(data)
    except ValidationError as exc:
        raise SkillError(f"{path}: invalid frontmatter: {exc}") from exc
    return front.description
