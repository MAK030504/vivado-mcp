"""Unit tests for ProjectManager (no real Vivado required)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vivado_mcp.config import Config
from vivado_mcp.projects import ProjectManager, resolve_xpr_path
from vivado_mcp.vivado import CommandResult, Vivado, VivadoVersionInfo


class FakeVivado(Vivado):
    """Vivado stub that records Tcl and optionally materializes .xpr files."""

    def __init__(
        self,
        *,
        create_xpr: bool = True,
        fail: bool = False,
        fail_message: str = "simulated failure",
        version: str = "2018.2",
    ) -> None:
        super().__init__(Config(), platform_name="Linux")
        self.create_xpr = create_xpr
        self.fail = fail
        self.fail_message = fail_message
        self.version = version
        self.scripts: list[str] = []

    def get_version(self) -> VivadoVersionInfo:
        return VivadoVersionInfo(
            installed=True,
            version=self.version,
            executable="/fake/vivado",
            platform="linux",
        )

    def run_tcl(
        self,
        script: str,
        *,
        timeout: float | None = 300.0,
        cwd: Path | None = None,
    ) -> CommandResult:
        self.scripts.append(script)
        if self.fail:
            from vivado_mcp.errors import VivadoExecutionError

            raise VivadoExecutionError(
                self.fail_message,
                returncode=1,
                stdout="",
                stderr="ERROR: [Common 17-69] simulated",
            )

        # Infer project paths from the generated Tcl for realistic markers.
        name = "counter"
        parent = Path("/tmp")
        part = "xc7a35tcpg236-1"
        if "create_project" in script:
            # create_project {name} {parent} -part {part}
            name = script.split("create_project {", 1)[1].split("}", 1)[0]
            parent_text = script.split("} {", 1)[1].split("}", 1)[0]
            parent = Path(parent_text)
            part = script.split("-part {", 1)[1].split("}", 1)[0]
            project_dir = parent / name
            xpr = project_dir / f"{name}.xpr"
            if self.create_xpr:
                project_dir.mkdir(parents=True, exist_ok=True)
                xpr.write_text("# fake xpr\n", encoding="utf-8")
            stdout = (
                f"VIVADO_MCP_STATUS=OK\n"
                f"VIVADO_MCP_PROJECT_NAME={name}\n"
                f"VIVADO_MCP_PROJECT_DIR={project_dir}\n"
                f"VIVADO_MCP_PROJECT_PART={part}\n"
            )
        elif "VIVADO_MCP_CLOSED=1" in script:
            stdout = "VIVADO_MCP_STATUS=OK\nVIVADO_MCP_CLOSED=1\n"
        else:
            # open_project via set _mcp_xpr {path} ... open_project $_mcp_xpr
            if "set _mcp_xpr {" in script:
                xpr_text = script.split("set _mcp_xpr {", 1)[1].split("}", 1)[0]
            else:
                xpr_text = script.split("open_project {", 1)[1].split("}", 1)[0]
            xpr = Path(xpr_text)
            stdout = (
                f"VIVADO_MCP_STATUS=OK\n"
                f"VIVADO_MCP_PROJECT_NAME={xpr.stem}\n"
                f"VIVADO_MCP_PROJECT_DIR={xpr.parent}\n"
                f"VIVADO_MCP_PROJECT_PART=xc7a35tcpg236-1\n"
            )
        return CommandResult(returncode=0, stdout=stdout, stderr="", args=("vivado",))


def test_create_project_success(tmp_path: Path) -> None:
    vivado = FakeVivado()
    manager = ProjectManager(vivado)
    result = manager.create_project(
        name="counter",
        path=str(tmp_path),
        part="xc7a35tcpg236-1",
    )
    assert result.success is True
    assert result.project is not None
    assert result.project.name == "counter"
    assert result.project.part == "xc7a35tcpg236-1"
    assert result.vivado_version == "2018.2"
    assert Path(result.project.xpr or "").exists()
    assert "create_project {counter}" in vivado.scripts[0]
    assert tmp_path.as_posix() in vivado.scripts[0].replace("\\", "/")


def test_create_project_windows_path_with_spaces(tmp_path: Path) -> None:
    parent = tmp_path / "Vivado Projects"
    parent.mkdir()
    vivado = FakeVivado()
    manager = ProjectManager(vivado)
    result = manager.create_project(
        name="blink",
        path=str(parent),
        part="xc7a35tcpg236-1",
    )
    assert result.success is True
    script = vivado.scripts[0]
    assert "{blink}" in script
    assert "Vivado Projects" in script


def test_create_project_rejects_existing(tmp_path: Path) -> None:
    project_dir = tmp_path / "counter"
    project_dir.mkdir()
    (project_dir / "counter.xpr").write_text("existing\n", encoding="utf-8")
    manager = ProjectManager(FakeVivado())
    result = manager.create_project(
        name="counter",
        path=str(tmp_path),
        part="xc7a35tcpg236-1",
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "ProjectAlreadyExistsError"


def test_create_project_invalid_name(tmp_path: Path) -> None:
    result = ProjectManager(FakeVivado()).create_project(
        name="bad name",
        path=str(tmp_path),
        part="xc7a35tcpg236-1",
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "InvalidProjectPathError"


def test_create_project_vivado_failure(tmp_path: Path) -> None:
    result = ProjectManager(FakeVivado(fail=True)).create_project(
        name="counter",
        path=str(tmp_path),
        part="xc7a35tcpg236-1",
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "VivadoExecutionError"
    assert "vivado_output" in result.error


def test_open_project_missing(tmp_path: Path) -> None:
    result = ProjectManager(FakeVivado()).open_project(str(tmp_path / "missing.xpr"))
    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "ProjectNotFoundError"


def test_open_project_success(tmp_path: Path) -> None:
    xpr = tmp_path / "counter.xpr"
    xpr.write_text("# xpr\n", encoding="utf-8")
    result = ProjectManager(FakeVivado()).open_project(str(xpr))
    assert result.success is True
    assert result.project is not None
    assert result.project.name == "counter"
    assert result.project.xpr == str(xpr)


def test_close_project_success(tmp_path: Path) -> None:
    xpr = tmp_path / "counter.xpr"
    xpr.write_text("# xpr\n", encoding="utf-8")
    result = ProjectManager(FakeVivado()).close_project(str(xpr))
    assert result.success is True
    assert result.project is not None
    assert "close_project" in result.message.lower() or result.success


def test_resolve_xpr_from_directory(tmp_path: Path) -> None:
    project_dir = tmp_path / "counter"
    project_dir.mkdir()
    xpr = project_dir / "counter.xpr"
    xpr.write_text("# xpr\n", encoding="utf-8")
    assert resolve_xpr_path(project_dir) == xpr


def test_resolve_xpr_multiple_files_error(tmp_path: Path) -> None:
    (tmp_path / "a.xpr").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.xpr").write_text("b\n", encoding="utf-8")
    with pytest.raises(Exception) as exc_info:
        resolve_xpr_path(tmp_path)
    assert "Multiple" in str(exc_info.value)


def test_create_project_missing_vivado(tmp_path: Path) -> None:
    class MissingVivado(FakeVivado):
        def get_version(self) -> VivadoVersionInfo:
            return VivadoVersionInfo(
                installed=False,
                version=None,
                executable=None,
                platform="linux",
                error="vivado_not_found",
                message="not installed",
            )

    result = ProjectManager(MissingVivado()).create_project(
        name="counter",
        path=str(tmp_path),
        part="xc7a35tcpg236-1",
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "VivadoNotFoundError"
