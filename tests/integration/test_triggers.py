"""Integration tests for the durable local-trigger queue and consumer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from newbot.adapters.stores.trigger_queue import TriggerQueue
from newbot.app.triggers import TriggerConsumer
from newbot.domain.envelope import InboundEnvelope
from newbot.domain.errors import ProviderError, TriggerError
from newbot.domain.turn import TurnStatus


def _record(root: Path, delivery_id: str) -> dict[str, object]:
    text = (root / f"{delivery_id}.json").read_text(encoding="utf-8")
    loaded: dict[str, object] = json.loads(text)
    return loaded


def test_enqueue_is_deduplicated_by_delivery_id(tmp_path: Path) -> None:
    queue = TriggerQueue(tmp_path)

    first = queue.enqueue("ci", "ops", "first", delivery_id="delivery-1")
    second = queue.enqueue("ci", "ops", "second", delivery_id="delivery-1")

    assert first == second == "delivery-1"
    assert [delivery.text for delivery in queue.claim()] == ["first"]


def test_a_claimed_delivery_is_redelivered_until_terminal(tmp_path: Path) -> None:
    queue = TriggerQueue(tmp_path)
    queue.enqueue("ci", "ops", "build failed")

    first = queue.claim()
    second = queue.claim()

    assert [delivery.delivery_id for delivery in second] == [
        delivery.delivery_id for delivery in first
    ]

    queue.complete(first[0].delivery_id)
    assert queue.claim() == ()


def test_a_failed_delivery_is_never_retried(tmp_path: Path) -> None:
    queue = TriggerQueue(tmp_path)
    delivery_id = queue.enqueue("ci", "ops", "boom")
    queue.claim()

    queue.fail(delivery_id, "turn failed")

    assert queue.claim() == ()
    record = _record(tmp_path, delivery_id)
    assert record["state"] == "failed"
    assert record["reason"] == "turn failed"


def test_an_unreadable_delivery_is_quarantined(tmp_path: Path) -> None:
    queue = TriggerQueue(tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    assert queue.claim() == ()

    assert (tmp_path / "broken.invalid").is_file()
    assert not (tmp_path / "broken.json").exists()


def test_invalid_delivery_id_is_rejected(tmp_path: Path) -> None:
    queue = TriggerQueue(tmp_path)

    with pytest.raises(TriggerError):
        queue.enqueue("ci", "ops", "hello", delivery_id="../escape")


async def test_consumer_completes_a_delivered_trigger(tmp_path: Path) -> None:
    queue = TriggerQueue(tmp_path)
    delivery_id = queue.enqueue("ci", "ops", "build failed")
    seen: list[InboundEnvelope] = []

    async def submit(envelope: InboundEnvelope) -> TurnStatus:
        seen.append(envelope)
        return TurnStatus.COMPLETED

    consumer = TriggerConsumer(queue, transport="webui", submit=submit)

    assert await consumer.consume() == 1

    assert seen[0].transport == "webui"
    assert seen[0].conversation_id == "ops"
    assert seen[0].text == "build failed"
    assert _record(tmp_path, delivery_id)["state"] == "done"


async def test_consumer_marks_a_failed_turn_failed(tmp_path: Path) -> None:
    queue = TriggerQueue(tmp_path)
    delivery_id = queue.enqueue("ci", "ops", "boom")

    async def submit(_envelope: InboundEnvelope) -> TurnStatus:
        return TurnStatus.FAILED

    consumer = TriggerConsumer(queue, transport="webui", submit=submit)

    assert await consumer.consume() == 1

    assert _record(tmp_path, delivery_id)["state"] == "failed"
    assert queue.claim() == ()


async def test_consumer_marks_a_raising_submission_failed(tmp_path: Path) -> None:
    queue = TriggerQueue(tmp_path)
    delivery_id = queue.enqueue("ci", "ops", "boom")

    async def submit(_envelope: InboundEnvelope) -> TurnStatus:
        raise ProviderError("provider down")

    consumer = TriggerConsumer(queue, transport="webui", submit=submit)

    assert await consumer.consume() == 1

    record = _record(tmp_path, delivery_id)
    assert record["state"] == "failed"
    assert record["reason"] == "provider down"
