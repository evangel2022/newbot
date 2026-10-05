"""Curation interpreter that plans durable-file edits with one provider call."""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, ValidationError

from newbot.domain.curation import CurationEdit, DurableFile
from newbot.domain.errors import CurationError, ProviderError
from newbot.domain.journal import JournalEntry
from newbot.domain.message import Message, Role
from newbot.domain.provider import Completed, ModelRequest
from newbot.ports.provider import ProviderPort

_PROMPT = (
    "You maintain an agent's long-term memory files. You receive new conversation "
    "summaries and the current contents of the durable files. Return the files that "
    "should change and their complete new content. Make the smallest change that keeps "
    "memory coherent: preserve unrelated content verbatim, never invent facts, and omit "
    "files that need no change. Reply with JSON only, shaped exactly like "
    '{"files": [{"path": "<path>", "content": "<complete new content>"}]}; '
    'reply with {"files": []} when nothing should change.'
)


class _WireEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str


class _WirePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[_WireEdit] = []


class ProviderCurator:
    """Plans durable-file edits by asking the configured provider."""

    def __init__(self, provider: ProviderPort, *, model: str) -> None:
        self._provider = provider
        self._model = model

    async def interpret(
        self, entries: Sequence[JournalEntry], files: Sequence[DurableFile]
    ) -> tuple[CurationEdit, ...]:
        request = ModelRequest(
            model=self._model,
            system=_PROMPT,
            messages=(Message(role=Role.USER, content=_render(entries, files)),),
        )
        final: Message | None = None
        async for event in self._provider.stream(request):
            if isinstance(event, Completed):
                final = event.message
        if final is None:
            raise ProviderError("provider stream ended without a completion")
        return _parse_plan(final.content)


def _render(entries: Sequence[JournalEntry], files: Sequence[DurableFile]) -> str:
    lines = ["## New summaries", ""]
    lines.extend(f"- [{entry.cursor}] {entry.summary}" for entry in entries)
    lines.extend(["", "## Current files", ""])
    for file in files:
        lines.extend((f"### {file.path}", "", file.content, ""))
    return "\n".join(lines)


def _parse_plan(content: str) -> tuple[CurationEdit, ...]:
    try:
        plan = _WirePlan.model_validate(json.loads(_strip_fence(content)))
    except (ValidationError, ValueError) as exc:
        raise CurationError(f"curation response was not usable: {exc}") from exc
    return tuple(
        CurationEdit(path=edit.path, content=edit.content) for edit in plan.files
    )


def _strip_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
