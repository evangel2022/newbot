"""The agent-facing tool that loads workspace skills on demand."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from newbot.domain.errors import ToolError
from newbot.domain.skill import Skill
from newbot.domain.tool import ToolSpec
from newbot.ports.tools import ToolContext
from newbot.tools.base import ToolOutput, require_string

_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "read"],
            "description": "List the available skills, or read one by name.",
        },
        "name": {
            "type": "string",
            "description": "The skill to read; read needs it.",
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}


class SkillTool:
    """Lists workspace skills and returns one skill's full instructions.

    The summary in the system prompt only carries names and descriptions, so
    a skill's body reaches the model only when the model asks for it.
    """

    def __init__(self, skills: Sequence[Skill]) -> None:
        self._skills = {skill.name: skill for skill in skills}
        self.spec = ToolSpec(
            name="skill",
            description=(
                "List the workspace skills, or read one to get its full "
                "instructions before following them."
            ),
            parameters=_SCHEMA,
        )

    async def invoke(
        self, arguments: Mapping[str, object], ctx: ToolContext
    ) -> ToolOutput:
        action = require_string(arguments, "action")
        if action == "list":
            return ToolOutput(text=self._list())
        if action == "read":
            return ToolOutput(text=self._read(require_string(arguments, "name")))
        raise ToolError(f"unknown action {action!r}; expected list or read")

    def _list(self) -> str:
        return "\n".join(
            f"- {name}: {self._skills[name].description}"
            for name in sorted(self._skills)
        )

    def _read(self, name: str) -> str:
        skill = self._skills.get(name)
        if skill is None:
            known = ", ".join(sorted(self._skills)) or "none"
            raise ToolError(f"unknown skill {name!r}; known skills: {known}")
        return skill.body
