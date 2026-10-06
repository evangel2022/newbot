"""Integration tests for the scheduled-job registry and its runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from newbot.adapters.stores.json_jobs import JsonJobStore
from newbot.domain.errors import CronError

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _store(tmp_path: Path) -> JsonJobStore:
    return JsonJobStore(tmp_path / "cron")


def test_a_job_round_trips_through_the_registry(tmp_path: Path) -> None:
    store = _store(tmp_path)

    job = store.add(
        transport="webui",
        conversation="ops",
        prompt="check the build",
        next_run_at=NOW + timedelta(seconds=30),
        every_seconds=60,
    )

    listed = store.jobs()
    assert [item.id for item in listed] == [job.id]
    assert listed[0].transport == "webui"
    assert listed[0].conversation == "ops"
    assert listed[0].prompt == "check the build"
    assert listed[0].next_run_at == NOW + timedelta(seconds=30)
    assert listed[0].every_seconds == 60


def test_a_registry_written_by_the_store_reloads_from_disk(tmp_path: Path) -> None:
    job = _store(tmp_path).add(
        transport="telegram", conversation="42", prompt="ping", next_run_at=NOW
    )

    assert JsonJobStore(tmp_path / "cron").jobs()[0].id == job.id


def test_a_naive_schedule_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CronError):
        _store(tmp_path).add(
            transport="webui",
            conversation="ops",
            prompt="check",
            next_run_at=datetime(2026, 10, 5, 12, 0),
        )


def test_remove_reports_whether_the_job_existed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.add(
        transport="webui", conversation="ops", prompt="check", next_run_at=NOW
    )

    assert store.remove("missing") is False
    assert store.remove(job.id) is True
    assert store.jobs() == ()


def test_remove_rejects_an_id_that_is_not_a_job_id(tmp_path: Path) -> None:
    with pytest.raises(CronError):
        _store(tmp_path).remove("../escape")


def test_dispatch_returns_due_jobs_and_advances_recurring_ones(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    due = store.add(
        transport="webui",
        conversation="ops",
        prompt="tick",
        next_run_at=NOW,
        every_seconds=60,
    )
    store.add(
        transport="webui",
        conversation="ops",
        prompt="later",
        next_run_at=NOW + timedelta(seconds=5),
    )

    dispatched = store.dispatch_due(NOW)

    assert [job.id for job in dispatched] == [due.id]
    remaining = store.jobs()
    assert [job.prompt for job in remaining] == ["tick", "later"]
    assert remaining[0].next_run_at == NOW + timedelta(seconds=60)


def test_dispatch_skips_the_runs_missed_while_the_host_was_down(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.add(
        transport="webui",
        conversation="ops",
        prompt="tick",
        next_run_at=NOW - timedelta(hours=3),
        every_seconds=60,
    )

    dispatched = store.dispatch_due(NOW)

    assert len(dispatched) == 1
    assert store.jobs()[0].next_run_at == NOW + timedelta(seconds=60)


def test_dispatch_drops_a_one_shot_job_that_is_overdue(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(
        transport="webui",
        conversation="ops",
        prompt="once",
        next_run_at=NOW - timedelta(seconds=1),
    )

    dispatched = store.dispatch_due(NOW)

    assert [job.prompt for job in dispatched] == ["once"]
    assert store.jobs() == ()


def test_dispatch_leaves_future_jobs_alone(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(
        transport="webui",
        conversation="ops",
        prompt="later",
        next_run_at=NOW + timedelta(seconds=1),
    )

    assert store.dispatch_due(NOW) == ()
    assert len(store.jobs()) == 1


def test_a_corrupt_registry_is_quarantined(tmp_path: Path) -> None:
    root = tmp_path / "cron"
    root.mkdir()
    (root / "jobs.json").write_text("{not json", encoding="utf-8")

    assert JsonJobStore(root).jobs() == ()
    assert (root / "jobs.invalid.json").is_file()
    assert not (root / "jobs.json").exists()


@pytest.mark.parametrize(
    "record",
    [
        {
            "id": "a",
            "transport": "webui",
            "conversation": "c",
            "prompt": "p",
            "next_run_at": "2026-10-05T12:00:00+00:00",
            "surprise": 1,
        },
        {
            "id": "a",
            "transport": "webui",
            "conversation": "c",
            "prompt": "p",
            "next_run_at": "2026-10-05T12:00:00",
        },
    ],
    ids=["unknown-field", "naive-timestamp"],
)
def test_an_unusable_record_is_quarantined(
    tmp_path: Path, record: dict[str, object]
) -> None:
    root = tmp_path / "cron"
    root.mkdir()
    (root / "jobs.json").write_text(json.dumps({"jobs": [record]}), encoding="utf-8")

    assert JsonJobStore(root).jobs() == ()
    assert (root / "jobs.invalid.json").is_file()
