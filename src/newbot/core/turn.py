"""The channel-facing turn engine."""

from __future__ import annotations

import asyncio
from pathlib import Path

from newbot.core.context import ContextAssembler
from newbot.core.hub import EventHub
from newbot.core.reasoning import ReasoningLoop
from newbot.domain.agent import AgentDefinition
from newbot.domain.envelope import InboundEnvelope, OutboundEnvelope
from newbot.domain.errors import NewbotError
from newbot.domain.events import TurnCompleted, TurnFailed, TurnStarted
from newbot.domain.message import Message, Role
from newbot.domain.session import SessionKey
from newbot.ports.sessions import SessionServicePort
from newbot.ports.tools import ToolContext


class TurnEngine:
    """Owns one active turn per session: assemble, reason, deliver."""

    def __init__(
        self,
        *,
        hub: EventHub,
        reasoning: ReasoningLoop,
        assembler: ContextAssembler,
        agent: AgentDefinition,
        workspace_root: Path,
        sessions: SessionServicePort,
    ) -> None:
        self._hub = hub
        self._reasoning = reasoning
        self._assembler = assembler
        self._agent = agent
        self._workspace_root = workspace_root
        self._sessions = sessions
        self._locks: dict[SessionKey, asyncio.Lock] = {}

    async def handle(self, envelope: InboundEnvelope) -> None:
        """Serialize and run the turn for the envelope's session."""
        session = SessionKey(
            transport=envelope.transport, conversation=envelope.conversation_id
        )
        lock = self._locks.get(session)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session] = lock
        async with lock:
            await self._run_turn(session, envelope)

    async def _run_turn(self, session: SessionKey, envelope: InboundEnvelope) -> None:
        await self._hub.publish(TurnStarted(session=session))
        user_message = Message(role=Role.USER, content=envelope.text)
        ctx = ToolContext(session=session, workspace_root=self._workspace_root)
        try:
            history = await self._sessions.history(session)
            request = self._assembler.assemble((*history, user_message))
            result = await self._reasoning.run(
                request,
                session=session,
                sink=self._hub,
                ctx=ctx,
                budget=self._agent.budget,
            )
            await self._sessions.record(session, (user_message, *result.produced))
        except NewbotError as exc:
            await self._hub.publish(TurnFailed(session=session, message=str(exc)))
            return
        if result.message.content:
            await self._hub.emit(
                OutboundEnvelope(
                    transport=session.transport,
                    conversation_id=session.conversation,
                    text=result.message.content,
                )
            )
        await self._hub.publish(TurnCompleted(session=session, status=result.status))
