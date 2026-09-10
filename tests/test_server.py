"""Smoke tests for the MCP server module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import vivado_mcp.server as server_module
from vivado_mcp.config import Config
from vivado_mcp.vivado import Vivado, VivadoVersionInfo


def test_get_vivado_version_tool_delegates(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    executable = tmp_path / "vivado"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)

    expected = VivadoVersionInfo(
        installed=True,
        version="2024.2",
        executable=str(executable),
        platform="linux",
    )

    class StubVivado(Vivado):
        def get_version(self) -> VivadoVersionInfo:
            return expected

    monkeypatch.setattr(
        server_module,
        "_build_vivado",
        lambda: StubVivado(Config(vivado_path=executable), platform_name="Linux"),
    )

    result: dict[str, Any] = server_module.get_vivado_version()
    assert result["installed"] is True
    assert result["version"] == "2024.2"
    assert result["executable"] == str(executable)
    assert result["platform"] == "linux"


def test_mcp_server_registers_get_vivado_version() -> None:
    tool_names = {tool.name for tool in server_module.mcp._tool_manager.list_tools()}
    assert "get_vivado_version" in tool_names
