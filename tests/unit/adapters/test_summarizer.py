"""Contract tests for the provider-backed summarizer."""

from __future__ import annotations

import pytest

from newbot.adapters.summarizers.provider import ProviderSummarizer
from newbot.domain.errors import ProviderError
from newbot.domain.message import Message, Role
from support import ScriptedProvider


async def test_summarize_sends_the_messages_without_tools() -> None:
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content="brief")])
    messages = (Message(role=Role.USER, content="hi"),)

    summary = await ProviderSummarizer(provider, model="m").summarize(messages)

    assert summary == "brief"
    request = provider.requests[0]
    assert request.model == "m"
    assert request.messages == messages
    assert request.tools == ()
    assert request.system


async def test_summarize_rejects_an_empty_completion() -> None:
    provider = ScriptedProvider([Message(role=Role.ASSISTANT, content="  ")])

    with pytest.raises(ProviderError):
        await ProviderSummarizer(provider, model="m").summarize(
            (Message(role=Role.USER, content="hi"),)
        )
