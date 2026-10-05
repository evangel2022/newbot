"""Contract tests for the reasoning loop's tool dispatch and iteration budget."""

from __future__ import annotations

from pathlib import Path

from newbot.core.reasoning import ReasoningLoop
from newbot.domain.message import Message, Role
from newbot.domain.provider import ModelRequest
from newbot.domain.session import SessionKey
from newbot.domain.tool import ToolCall, ToolResult, ToolSpec
from newbot.domain.turn import Budget, TurnStatus
from newbot.ports.tools import ToolContext
from support import RecordingSink, ScriptedProvider, StubRegistry

SESSION = SessionKey(transport="cli", conversation="default")
CTX = ToolContext(session=SESSION, workspace_root=Path("."))
REQUEST = ModelRequest(
    model="test-model",
    system="be terse",
    messages=(Message(role=Role.USER, content="read the note"),),
)
SPEC = ToolSpec(name="echo", description="echo", parameters={"type": "object"})


def _tool_call_message(call_id: str) -> Message:
    return Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=(ToolCall(id=call_id, name="echo", arguments='{"text":"hi"}'),),
    )


async def test_tool_calls_are_dispatched_and_fed_back() -> None:
    provider = ScriptedProvider(
        [_tool_call_message("c1"), Message(role=Role.ASSISTANT, content="done")]
    )
    registry = StubRegistry(
        specs=(SPEC,),
        results={"echo": ToolResult(call_id="c1", content="ran echo")},
    )

    result = await ReasoningLoop(provider, registry).run(
        REQUEST, session=SESSION, sink=RecordingSink(), ctx=CTX, budget=Budget(4)
    )

    assert result.status is TurnStatus.COMPLETED
    assert result.message.content == "done"
    assert [call.name for call in registry.calls] == ["echo"]
    follow_up = provider.requests[1].messages
    assert follow_up[-2].tool_calls[0].id == "c1"
    assert follow_up[-1].role is Role.TOOL
    assert follow_up[-1].content == "ran echo"
    assert follow_up[-1].tool_call_id == "c1"


async def test_iteration_budget_stops_before_executing_tools() -> None:
    provider = ScriptedProvider([_tool_call_message("c1")])
    registry = StubRegistry(specs=(SPEC,))

    result = await ReasoningLoop(provider, registry).run(
        REQUEST, session=SESSION, sink=RecordingSink(), ctx=CTX, budget=Budget(1)
    )

    assert result.status is TurnStatus.BUDGET_EXCEEDED
    assert result.message.tool_calls[0].id == "c1"
    assert registry.calls == []
    assert len(provider.requests) == 1
