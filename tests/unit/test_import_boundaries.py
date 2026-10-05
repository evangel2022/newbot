"""Guard the dependency rule (ADR-001/A2) with a static import check."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "newbot"

FORBIDDEN: dict[str, set[str]] = {
    "domain": {
        "ports",
        "core",
        "policy",
        "adapters",
        "app",
        "cli",
        "config",
        "tools",
        "session",
        "memory",
        "extensions",
    },
    "ports": {"core", "adapters", "app", "cli"},
    "core": {
        "adapters",
        "app",
        "cli",
        "session",
        "memory",
        "extensions",
        "tools",
        "config",
    },
    "config": {"core", "adapters", "tools"},
    "policy": {"core", "adapters", "app", "cli", "tools"},
    "session": {"core", "adapters"},
    "memory": {
        "core",
        "adapters",
        "app",
        "cli",
        "tools",
        "config",
        "session",
        "extensions",
    },
    "tools": {"core", "adapters", "app", "cli"},
    "adapters": {"core", "app", "cli"},
    "app": {"cli"},
}


def _imported_newbot_layers(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    layers: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules = [node.module]
        else:
            continue
        for module in modules:
            parts = module.split(".")
            if len(parts) >= 2 and parts[0] == "newbot":
                layers.append(parts[1])
    return layers


def test_layers_only_import_inward() -> None:
    violations: list[str] = []
    for layer, forbidden in FORBIDDEN.items():
        for path in (SRC / layer).rglob("*.py"):
            for imported in _imported_newbot_layers(path):
                if imported in forbidden:
                    violations.append(f"{path.relative_to(SRC)} imports {imported}")

    assert violations == []
