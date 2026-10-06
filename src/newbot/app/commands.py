"""Runtime command handling: intercept known commands before a turn.

Commands are handled here rather than in the transports, so the CLI, chat,
and workbench clients stay thin (AGENTS.md).
"""

from __future__ import annotations

from newbot.core.delegation import SubagentManager
from newbot.core.hub import EventHub
from newbot.core.turn import TurnEngine
from newbot.domain.envelope import InboundEnvelope, OutboundEnvelope
from newbot.domain.session import SessionKey
from newbot.domain.turn import TurnStatus
from newbot.ports.sessions import SessionServicePort

_HELP = (
    "commands:\n"
    "  /new   stop this conversation's tasks and start it over\n"
    "  /stop  stop this conversation's running subagent tasks\n"
    "  /help  show this help\n"
)


class CommandRouter:
    """Intercepts known commands; every other message runs a turn."""

    def __init__(
        self,
        *,
        engine: TurnEngine,
        hub: EventHub,
        subagents: SubagentManager,
        sessions: SessionServicePort,
    ) -> None:
        self._engine = engine
        self._hub = hub
        self._subagents = subagents
        self._sessions = sessions

    async def handle(self, envelope: InboundEnvelope) -> TurnStatus:
        """Handle a command, or delegate the message to the turn engine."""
        reply = await self.reply(envelope)
        if reply is None:
            return await self._engine.handle(envelope)
        if envelope.reply:
            await self._hub.emit(
                OutboundEnvelope(
                    transport=envelope.transport,
                    conversation_id=envelope.conversation_id,
                    text=reply,
                )
            )
        return TurnStatus.COMPLETED

    async def reply(self, envelope: InboundEnvelope) -> str | None:
        """Return the reply text for a known command, else ``None``.

        The interactive CLI calls this directly and writes the reply to its
        prompt stream; transports use :meth:`handle`.
        """
        text = envelope.text.strip()
        session = SessionKey(envelope.transport, envelope.conversation_id)
        if text == "/stop":
            stopped = await self._subagents.cancel_session(session)
            if stopped:
                return f"stopped {len(stopped)} subagent task(s)"
            return "no running subagent tasks"
        if text == "/new":
            stopped = await self._subagents.cancel_session(session)
            await self._sessions.reset(session)
            if stopped:
                return (
                    f"stopped {len(stopped)} subagent task(s); "
                    "started a new conversation"
                )
            return "started a new conversation"
        if text == "/help":
            return _HELP
        return None
