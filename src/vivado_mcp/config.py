"""Configuration for Vivado MCP.

Users configure Vivado without editing Python source. Supported sources
(highest priority first for the executable path):

1. Explicit ``vivado_path`` passed to :class:`Config`
2. ``VIVADO_PATH`` environment variable
3. Automatic detection (handled by the Vivado abstraction layer)

Optional settings used by later milestones are already represented so
configuration stays stable as the project grows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ENV_VIVADO_PATH = "VIVADO_PATH"
ENV_VIVADO_VERSION = "VIVADO_VERSION"
ENV_VIVADO_WORKSPACE = "VIVADO_WORKSPACE"


@dataclass(frozen=True, slots=True)
class Config:
    """Runtime configuration for Vivado MCP.

    Attributes:
        vivado_path: Explicit path to the Vivado executable, if configured.
        preferred_version: Optional preferred Vivado version string
            (for example ``\"2024.2\"``) used during auto-detection.
        workspace: Optional default workspace / project directory.
    """

    vivado_path: Path | None = None
    preferred_version: str | None = None
    workspace: Path | None = None

    @classmethod
    def from_env(
        cls,
        *,
        environ: dict[str, str] | None = None,
        vivado_path: str | Path | None = None,
        preferred_version: str | None = None,
        workspace: str | Path | None = None,
    ) -> Config:
        """Build configuration from explicit values and environment variables.

        Explicit keyword arguments override environment variables.
        """
        env = environ if environ is not None else os.environ

        path_value = vivado_path if vivado_path is not None else env.get(ENV_VIVADO_PATH)
        version_value = (
            preferred_version
            if preferred_version is not None
            else env.get(ENV_VIVADO_VERSION)
        )
        workspace_value = (
            workspace if workspace is not None else env.get(ENV_VIVADO_WORKSPACE)
        )

        return cls(
            vivado_path=_optional_path(path_value),
            preferred_version=_optional_str(version_value),
            workspace=_optional_path(workspace_value),
        )


def _optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_path(value: str | Path | None) -> Path | None:
    text = _optional_str(str(value) if value is not None else None)
    if text is None:
        return None
    return Path(text).expanduser()
