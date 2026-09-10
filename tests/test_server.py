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


def test_mcp_server_registers_project_tools() -> None:
    tool_names = {tool.name for tool in server_module.mcp._tool_manager.list_tools()}
    assert "create_project" in tool_names
    assert "open_project" in tool_names
    assert "close_project" in tool_names


def test_mcp_server_registers_source_tools() -> None:
    tool_names = {tool.name for tool in server_module.mcp._tool_manager.list_tools()}
    assert "create_rtl_file" in tool_names
    assert "add_source" in tool_names
    assert "remove_source" in tool_names
    assert "list_sources" in tool_names


def test_mcp_server_registers_simulation_tools() -> None:
    tool_names = {tool.name for tool in server_module.mcp._tool_manager.list_tools()}
    assert "create_testbench" in tool_names
    assert "run_simulation" in tool_names
    assert "get_simulation_status" in tool_names


def test_mcp_server_registers_synthesis_tools() -> None:
    tool_names = {tool.name for tool in server_module.mcp._tool_manager.list_tools()}
    assert "run_synthesis" in tool_names
    assert "get_utilization" in tool_names
    assert "get_timing" in tool_names


def test_mcp_server_registers_implementation_tools() -> None:
    tool_names = {tool.name for tool in server_module.mcp._tool_manager.list_tools()}
    assert "run_implementation" in tool_names
    assert "get_implementation_status" in tool_names
    assert "get_implemented_utilization" in tool_names
    assert "get_timing" in tool_names


def test_mcp_server_registers_bitstream_tools() -> None:
    tool_names = {tool.name for tool in server_module.mcp._tool_manager.list_tools()}
    assert "generate_bitstream" in tool_names
    assert "get_bitstream_status" in tool_names
    assert "get_bitstream_path" in tool_names


def test_create_project_tool_delegates(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from vivado_mcp.projects import ProjectInfo, ProjectManager, ProjectOperationResult

    expected = ProjectOperationResult(
        success=True,
        project=ProjectInfo(
            name="counter",
            path=str(tmp_path / "counter"),
            part="xc7a35tcpg236-1",
            xpr=str(tmp_path / "counter" / "counter.xpr"),
        ),
        vivado_version="2018.2",
        message="Created Vivado project 'counter'.",
    )

    class StubManager(ProjectManager):
        def create_project(self, name: str, path: str, part: str) -> ProjectOperationResult:
            assert name == "counter"
            assert part == "xc7a35tcpg236-1"
            return expected

    monkeypatch.setattr(server_module, "_build_project_manager", lambda: StubManager())
    result = server_module.create_project(
        name="counter",
        path=str(tmp_path),
        part="xc7a35tcpg236-1",
    )
    assert result["success"] is True
    assert result["project"]["name"] == "counter"
