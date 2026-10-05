"""Integration tests for the file-system versioning vault."""

from __future__ import annotations

from pathlib import Path

import pytest

from newbot.adapters.stores.fs_vault import FsVault
from newbot.domain.errors import VersionError


def _vault(tmp_path: Path) -> tuple[FsVault, Path]:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    knowledge = workspace / "memory" / "knowledge.md"
    return FsVault(tmp_path / "vault", workspace), knowledge


async def test_write_lists_versions_newest_first_and_skips_unchanged(
    tmp_path: Path,
) -> None:
    vault, knowledge = _vault(tmp_path)

    first = await vault.write(knowledge, "one")
    second = await vault.write(knowledge, "two")
    unchanged = await vault.write(knowledge, "two")

    assert second != first
    assert unchanged == second
    assert knowledge.read_text(encoding="utf-8") == "two"
    versions = await vault.history(knowledge)
    assert [version.version_id for version in versions] == [second, first]
    assert [version.path for version in versions] == ["memory/knowledge.md"] * 2
    assert [version.size for version in versions] == [3, 3]
    assert [version.change_set for version in versions] == [None, None]
    assert await vault.read(knowledge, first) == "one"


async def test_restore_writes_an_older_version_back(tmp_path: Path) -> None:
    vault, knowledge = _vault(tmp_path)
    first = await vault.write(knowledge, "one")
    await vault.write(knowledge, "two")

    await vault.restore(knowledge, first)

    assert knowledge.read_text(encoding="utf-8") == "one"
    versions = await vault.history(knowledge)
    assert versions[0].version_id == first
    assert len(versions) == 3


async def test_versions_lists_every_file_newest_first(tmp_path: Path) -> None:
    vault, knowledge = _vault(tmp_path)
    first = await vault.write(knowledge, "one")
    second = await vault.write(knowledge, "two")
    persona = await vault.write(knowledge.parent.parent / "persona.md", "voice")

    versions = await vault.versions()

    assert [version.version_id for version in versions] == [persona, second, first]
    assert [version.path for version in versions] == [
        "persona.md",
        "memory/knowledge.md",
        "memory/knowledge.md",
    ]


async def test_write_set_groups_versions_and_revert_set_rolls_the_pass_back(
    tmp_path: Path,
) -> None:
    vault, knowledge = _vault(tmp_path)
    persona = knowledge.parent.parent / "persona.md"
    baseline = await vault.write_set([(knowledge, "one"), (persona, "voice")])
    second = await vault.write_set([(knowledge, "two"), (persona, "new voice")])

    versions = await vault.versions()
    assert [version.change_set for version in versions] == [
        second,
        second,
        baseline,
        baseline,
    ]

    reverted = await vault.revert_set(second)

    assert reverted == ("memory/knowledge.md", "persona.md")
    assert knowledge.read_text(encoding="utf-8") == "one"
    assert persona.read_text(encoding="utf-8") == "voice"


async def test_revert_set_removes_files_the_pass_created(tmp_path: Path) -> None:
    vault, knowledge = _vault(tmp_path)
    created = await vault.write_set([(knowledge, "born")])
    assert knowledge.is_file()

    reverted = await vault.revert_set(created)

    assert reverted == ("memory/knowledge.md",)
    assert not knowledge.exists()


async def test_unknown_or_malformed_change_set_is_rejected(tmp_path: Path) -> None:
    vault, _ = _vault(tmp_path)

    with pytest.raises(VersionError):
        await vault.revert_set("0" * 16)
    with pytest.raises(VersionError):
        await vault.revert_set("not-a-change-set")


async def test_identical_content_in_two_files_records_distinct_versions(
    tmp_path: Path,
) -> None:
    vault, knowledge = _vault(tmp_path)
    first = await vault.write(knowledge, "same")
    second = await vault.write(knowledge.parent.parent / "persona.md", "same")

    assert first != second


async def test_unknown_or_malformed_version_is_rejected(tmp_path: Path) -> None:
    vault, knowledge = _vault(tmp_path)
    await vault.write(knowledge, "one")

    with pytest.raises(VersionError):
        await vault.read(knowledge, "0" * 16)
    with pytest.raises(VersionError):
        await vault.read(knowledge, "../../escape")


async def test_a_version_of_another_file_is_rejected(tmp_path: Path) -> None:
    vault, knowledge = _vault(tmp_path)
    version_id = await vault.write(knowledge.parent / "other.md", "other content")

    with pytest.raises(VersionError):
        await vault.restore(knowledge, version_id)
    assert not knowledge.exists()


async def test_paths_outside_the_workspace_are_rejected(tmp_path: Path) -> None:
    vault, _ = _vault(tmp_path)

    with pytest.raises(VersionError):
        await vault.write(tmp_path / "outside.md", "x")
    assert not (tmp_path / "outside.md").exists()


async def test_malformed_index_raises_version_error(tmp_path: Path) -> None:
    vault, knowledge = _vault(tmp_path)
    await vault.write(knowledge, "one")
    index = tmp_path / "vault" / "index.jsonl"
    index.write_text(
        index.read_text(encoding="utf-8") + "{not json}\n", encoding="utf-8"
    )

    with pytest.raises(VersionError):
        await vault.history(knowledge)
