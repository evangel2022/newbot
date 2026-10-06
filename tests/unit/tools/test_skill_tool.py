"""Unit tests for the skill tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.domain.errors import ToolError
from newbot.domain.session import SessionKey
from newbot.domain.skill import Skill
from newbot.ports.tools import ToolContext
from newbot.tools.skills import SkillTool

_SKILLS = (
    Skill(name="greet", description="Say hello", body="Do it warmly."),
    Skill(name="deploy", description="Ship it", body="Run the pipeline."),
)


def _context() -> ToolContext:
    return ToolContext(
        session=SessionKey(transport="cli", conversation="default"),
        workspace_root=Path("/tmp"),
    )


async def test_list_returns_every_skill_in_order() -> None:
    output = await SkillTool(_SKILLS).invoke({"action": "list"}, _context())

    assert output.text == "- deploy: Ship it\n- greet: Say hello"


async def test_read_returns_the_skill_body() -> None:
    output = await SkillTool(_SKILLS).invoke(
        {"action": "read", "name": "greet"}, _context()
    )

    assert output.text == "Do it warmly."


async def test_reading_an_unknown_skill_is_an_error() -> None:
    with pytest.raises(ToolError):
        await SkillTool(_SKILLS).invoke(
            {"action": "read", "name": "missing"}, _context()
        )


async def test_an_unknown_action_is_an_error() -> None:
    with pytest.raises(ToolError):
        await SkillTool(_SKILLS).invoke({"action": "drop"}, _context())
