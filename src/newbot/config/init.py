"""Create default configuration and workspace files (never overwrites)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from newbot.domain.errors import ConfigLoadError

_WORKSPACE_TOKEN = "__NEWBOT_WORKSPACE__"
_TEMPLATE = f"""\
# newbot configuration. Secrets stay as ${{ENV}} references; none are written here.
[provider]
# Any OpenAI-compatible chat-completions endpoint.
baseUrl = "https://api.openai.com/v1"
# Export this variable before running newbot.
apiKey = "${{NEWBOT_API_KEY}}"

[agent]
# Any model the endpoint serves.
model = "gpt-4o-mini"
workspace = "{_WORKSPACE_TOKEN}"
"""


class InitOutcome(StrEnum):
    """What ``initialize`` did with the config file."""

    CREATED = "created"
    EXISTS = "exists"


def initialize(config_file: Path, workspace: Path) -> InitOutcome:
    """Create the config file and workspace directory unless the file exists.

    An existing file is never rewritten or repaired: defaults are created only
    when the file is absent, and an invalid file is left for the loader to
    reject. The file is written as UTF-8 with LF endings and no BOM.
    """
    if config_file.exists():
        return InitOutcome.EXISTS
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        config_file.parent.mkdir(parents=True, exist_ok=True)
        text = _TEMPLATE.replace(_WORKSPACE_TOKEN, workspace.as_posix())
        config_file.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise ConfigLoadError(
            f"cannot create config file: {exc}", location=str(config_file)
        ) from exc
    return InitOutcome.CREATED
