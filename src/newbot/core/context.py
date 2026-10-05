"""Context assembly: build the ordered model request."""

from __future__ import annotations

from collections.abc import Sequence

from newbot.domain.agent import AgentDefinition
from newbot.domain.message import Message
from newbot.domain.provider import ModelRequest
from newbot.ports.tools import ToolRegistryPort


class ContextAssembler:
    """Builds a provider-ready request from the agent definition and history."""

    def __init__(self, agent: AgentDefinition, tools: ToolRegistryPort) -> None:
        self._agent = agent
        self._tools = tools

    def assemble(self, history: Sequence[Message]) -> ModelRequest:
        """Return the model request for the given conversation history."""
        return ModelRequest(
            model=self._agent.model,
            system=self._agent.system_prompt,
            messages=tuple(history),
            tools=self._tools.specs(),
        )
