"""Contract tests for the JSON subagent task registry."""

from __future__ import annotations

import json
from pathlib import Path

from newbot.adapters.stores.json_subagent_tasks import JsonSubagentTaskStore
from newbot.domain.session import SessionKey
from newbot.domain.subagent import SubagentStatus, SubagentTaskRecord


def _record(
    *,
    id: str = "task-1",
    status: SubagentStatus = SubagentStatus.COMPLETED,
    text: str = "done",
) -> SubagentTaskRecord:
    return SubagentTaskRecord(
        id=id,
        parent=SessionKey("cli", "default"),
        child=SessionKey("cli", "default:sub:1"),
        status=status,
        text=text,
    )


def test_round_trips_records(tmp_path: Path) -> None:
    JsonSubagentTaskStore(tmp_path).save(
        (_record(), _record(id="task-2", status=SubagentStatus.RUNNING, text="half"))
    )

    loaded = JsonSubagentTaskStore(tmp_path).load()

    assert [(item.id, item.status, item.text) for item in loaded] == [
        ("task-1", SubagentStatus.COMPLETED, "done"),
        ("task-2", SubagentStatus.RUNNING, "half"),
    ]
    assert loaded[0].parent == SessionKey("cli", "default")
    assert loaded[0].child == SessionKey("cli", "default:sub:1")


def test_a_missing_registry_loads_empty(tmp_path: Path) -> None:
    assert JsonSubagentTaskStore(tmp_path).load() == ()


def test_a_corrupt_registry_is_quarantined(tmp_path: Path) -> None:
    (tmp_path / "tasks.json").write_text("{not json", encoding="utf-8")

    assert JsonSubagentTaskStore(tmp_path).load() == ()
    assert (tmp_path / "tasks.invalid.json").is_file()
    assert not (tmp_path / "tasks.json").is_file()


def test_an_invalid_status_is_quarantined(tmp_path: Path) -> None:
    (tmp_path / "tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "task-1",
                        "transport": "cli",
                        "conversation": "default",
                        "child_transport": "cli",
                        "child_conversation": "default:sub:1",
                        "status": "bogus",
                        "text": "",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert JsonSubagentTaskStore(tmp_path).load() == ()
    assert (tmp_path / "tasks.invalid.json").is_file()
