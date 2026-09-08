"""Integration tests that require a real Vivado installation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from vivado_mcp.config import Config
from vivado_mcp.projects import ProjectManager
from vivado_mcp.vivado import Vivado


def _vivado_available() -> bool:
    try:
        info = Vivado(Config.from_env()).get_version()
    except Exception:
        return False
    return bool(info.installed)


@pytest.mark.integration
def test_real_vivado_create_open_close_project(tmp_path: Path) -> None:
    if not _vivado_available():
        pytest.skip("Vivado is not installed on this machine")

    manager = ProjectManager(Vivado(Config.from_env()))
    parent = tmp_path / "vivado_mcp_it"
    parent.mkdir()

    created = manager.create_project(
        name="proj_it_demo",
        path=str(parent),
        part="xc7a35tcpg236-1",
    )
    assert created.success is True, created.error
    assert created.project is not None
    xpr = Path(created.project.xpr or "")
    assert xpr.exists()

    opened = manager.open_project(str(xpr))
    assert opened.success is True, opened.error

    closed = manager.close_project(str(xpr))
    assert closed.success is True, closed.error

    # Cleanup project tree created by Vivado.
    shutil.rmtree(parent / "proj_it_demo", ignore_errors=True)
    for leftover in parent.glob("proj_it_demo*"):
        if leftover.is_dir():
            shutil.rmtree(leftover, ignore_errors=True)
        else:
            leftover.unlink(missing_ok=True)
