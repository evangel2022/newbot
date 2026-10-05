"""The immutable agent definition resolved at composition time."""

from __future__ import annotations

from dataclasses import dataclass

from newbot.domain.turn import Budget


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """The model-facing identity of one agent instance."""

    model: str
    system_prompt: str
    budget: Budget
