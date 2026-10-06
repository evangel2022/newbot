"""Contract tests for reading heartbeat tasks from the workspace file."""

from __future__ import annotations

from pathlib import Path

from newbot.app.heartbeat import read_active_tasks


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "HEARTBEAT.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_has_no_tasks(tmp_path: Path) -> None:
    assert read_active_tasks(tmp_path / "HEARTBEAT.md") == ()


def test_tasks_are_returned_in_order_and_scoped_to_the_section(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        "# Heartbeat\n"
        "\n"
        "## Active Tasks\n"
        "\n"
        "- Check the build\n"
        "* Report storms\n"
        "+ Third task\n"
        "\n"
        "## Done\n"
        "- Already handled\n",
    )

    assert read_active_tasks(path) == (
        "Check the build",
        "Report storms",
        "Third task",
    )


def test_section_without_bullets_has_no_tasks(tmp_path: Path) -> None:
    path = _write(tmp_path, "## Active Tasks\n\nNothing right now.\n")

    assert read_active_tasks(path) == ()


def test_file_without_the_section_has_no_tasks(tmp_path: Path) -> None:
    path = _write(tmp_path, "# Notes\n\n- unrelated\n")

    assert read_active_tasks(path) == ()


def test_indented_bullets_are_not_tasks(tmp_path: Path) -> None:
    path = _write(tmp_path, "## Active Tasks\n- top level\n  - nested detail\n")

    assert read_active_tasks(path) == ("top level",)
