"""Consume durable local-trigger deliveries into their bound sessions."""

from __future__ import annotations

import asyncio

from newbot.adapters.stores.trigger_queue import TriggerQueue
from newbot.domain.envelope import InboundEnvelope
from newbot.domain.errors import NewbotError
from newbot.domain.turn import TurnStatus
from newbot.ports.transports import InboundHandler


class TriggerConsumer:
    """Runs queued deliveries through the hub and records their outcome."""

    def __init__(
        self, queue: TriggerQueue, *, transport: str, submit: InboundHandler
    ) -> None:
        self._queue = queue
        self._transport = transport
        self._submit = submit

    async def consume(self) -> int:
        """Run every claimable delivery once; return how many were claimed."""
        deliveries = await asyncio.to_thread(self._queue.claim)
        for delivery in deliveries:
            try:
                status = await self._submit(
                    InboundEnvelope(
                        transport=self._transport,
                        conversation_id=delivery.conversation,
                        text=delivery.text,
                    )
                )
            except NewbotError as exc:
                await asyncio.to_thread(self._queue.fail, delivery.delivery_id, str(exc))
            else:
                if status is TurnStatus.FAILED:
                    await asyncio.to_thread(
                        self._queue.fail, delivery.delivery_id, "turn failed"
                    )
                else:
                    await asyncio.to_thread(self._queue.complete, delivery.delivery_id)
        return len(deliveries)
