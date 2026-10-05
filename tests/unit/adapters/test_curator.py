"""Contract tests for the provider-backed curation interpreter."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from newbot.adapters.curators.provider import ProviderCurator
from newbot.domain.curation import CurationEdit, DurableFile
from newbot.domain.errors import CurationError
from newbot.domain.journal import JournalEntry
from newbot.domain.message import Message, Role
from support import ScriptedProvider


def _entry(cursor: int, summary: str) -> JournalEntry:
    return JournalEntry(
        cursor=cursor, timestamp=datetime(2026, 10, 5, tzinfo=UTC), summary=summary
    )


async def test_interpret_returns_the_planned_edits() -> None:
    plan = {
        "files": [
            {"path": "memory/knowledge.md", "content": "- fact"},
            {"path": "user.md", "content": "name: A"},
        ]
    }
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content=json.dumps(plan))])

    edits = await ProviderCurator(provider, model="m").interpret(
        (_entry(3, "decided X"),),
        (DurableFile(path="memory/knowledge.md", content="old"),),
    )

    assert edits == (
        CurationEdit(path="memory/knowledge.md", content="- fact"),
        CurationEdit(path="user.md", content="name: A"),
    )
    request = provider.requests[0]
    assert request.model == "m"
    assert request.tools == ()
    assert "decided X" in request.messages[0].content
    assert "memory/knowledge.md" in request.messages[0].content
    assert "old" in request.messages[0].content


async def test_interpret_accepts_a_fenced_json_response() -> None:
    provider = ScriptedProvider(
        [Message(role=Role.ASSISTANT, content='```json\n{"files": []}\n```')]
    )

    assert await ProviderCurator(provider, model="m").interpret((), ()) == ()


async def test_interpret_rejects_an_unusable_response() -> None:
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content="not json")])

    with pytest.raises(CurationError):
        await ProviderCurator(provider, model="m").interpret((), ())
