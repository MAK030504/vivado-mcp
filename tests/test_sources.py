"""Unit tests for RTL/source management (no real Vivado required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vivado_mcp.config import Config
from vivado_mcp.errors import InvalidSourceError
from vivado_mcp.sources import (
    SourceManager,
    language_from_path,
    normalize_language,
    parse_source_list,
    resolve_rtl_filename,
)
from vivado_mcp.tcl import (
    build_add_source_tcl,
    build_list_sources_tcl,
    build_remove_source_tcl,
)
from vivado_mcp.vivado import CommandResult, Vivado, VivadoVersionInfo


def _make_project(tmp_path: Path, name: str = "demo") -> Path:
    xpr = tmp_path / f"{name}.xpr"
    xpr.write_text(f"# fake {name}\n", encoding="utf-8")
    return xpr


class FakeVivado(Vivado):
    def __init__(self, *, fail: bool = False, stdout: str = "") -> None:
        super().__init__(Config(), platform_name="Linux")
        self.fail = fail
        self.stdout = stdout
        self.scripts: list[str] = []

    def get_version(self) -> VivadoVersionInfo:
        return VivadoVersionInfo(
            installed=True,
            version="2018.2",
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
                "simulated vivado failure",
                returncode=1,
                stdout=self.stdout or "VIVADO_MCP_STATUS=ERROR\n",
                stderr="ERROR: simulated",
            )
        return CommandResult(
            returncode=0,
            stdout=self.stdout or "VIVADO_MCP_STATUS=OK\n",
            stderr="",
            args=("vivado",),
        )


def test_normalize_language() -> None:
    assert normalize_language("verilog") == "verilog"
    assert normalize_language("SystemVerilog") == "systemverilog"
    assert normalize_language("sv") == "systemverilog"
    with pytest.raises(InvalidSourceError):
        normalize_language("vhdl")


def test_resolve_rtl_filename_infers_extension() -> None:
    assert resolve_rtl_filename("counter", "verilog") == "counter.v"
    assert resolve_rtl_filename("top", "systemverilog") == "top.sv"
    assert resolve_rtl_filename("counter.v", "verilog") == "counter.v"


def test_resolve_rtl_filename_rejects_mismatch_and_traversal() -> None:
    with pytest.raises(InvalidSourceError):
        resolve_rtl_filename("counter.sv", "verilog")
    with pytest.raises(InvalidSourceError):
        resolve_rtl_filename("../etc/passwd.v", "verilog")
    with pytest.raises(InvalidSourceError):
        resolve_rtl_filename("subdir/counter.v", "verilog")
    with pytest.raises(InvalidSourceError):
        resolve_rtl_filename("counter.vhdl", "verilog")
    with pytest.raises(InvalidSourceError):
        resolve_rtl_filename("", "verilog")


def test_create_rtl_file_verilog_and_systemverilog(tmp_path: Path) -> None:
    _make_project(tmp_path)
    manager = SourceManager(FakeVivado())

    v_result = manager.create_rtl_file(
        project_path=str(tmp_path),
        filename="counter",
        code="module counter; endmodule\n",
        language="verilog",
    )
    assert v_result.success is True
    assert v_result.source_path is not None
    assert Path(v_result.source_path) == tmp_path / "rtl" / "counter.v"
    assert Path(v_result.source_path).read_text(encoding="utf-8") == (
        "module counter; endmodule\n"
    )

    sv_result = manager.create_rtl_file(
        project_path=str(tmp_path),
        filename="top.sv",
        code="module top; endmodule\n",
        language="systemverilog",
    )
    assert sv_result.success is True
    assert sv_result.language == "systemverilog"
    assert Path(sv_result.source_path or "").exists()


def test_create_rtl_file_rejects_existing(tmp_path: Path) -> None:
    _make_project(tmp_path)
    manager = SourceManager(FakeVivado())
    first = manager.create_rtl_file(
        str(tmp_path), "counter.v", "module counter; endmodule\n", "verilog"
    )
    assert first.success is True
    second = manager.create_rtl_file(
        str(tmp_path), "counter.v", "module other; endmodule\n", "verilog"
    )
    assert second.success is False
    assert second.error is not None
    assert second.error["type"] == "SourceAlreadyExistsError"


def test_create_rtl_file_rejects_invalid_language(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = SourceManager(FakeVivado()).create_rtl_file(
        str(tmp_path), "counter.v", "module counter; endmodule\n", "vhdl"
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "InvalidSourceError"


def test_add_source_success(tmp_path: Path) -> None:
    _make_project(tmp_path)
    source = tmp_path / "counter.v"
    source.write_text("module counter; endmodule\n", encoding="utf-8")
    fake = FakeVivado(
        stdout=(
            f"VIVADO_MCP_STATUS=OK\nVIVADO_MCP_SOURCE={source.as_posix()}\n"
            "VIVADO_MCP_FILESET=sources_1\n"
        )
    )
    result = SourceManager(fake).add_source(str(tmp_path), str(source))
    assert result.success is True
    assert "add_files -norecurse" in fake.scripts[0]
    assert "update_compile_order -fileset sources_1" in fake.scripts[0]


def test_add_source_to_sim_fileset(tmp_path: Path) -> None:
    _make_project(tmp_path)
    source = tmp_path / "sim" / "tb.v"
    source.parent.mkdir(parents=True)
    source.write_text("module tb; endmodule\n", encoding="utf-8")
    fake = FakeVivado(
        stdout=(
            f"VIVADO_MCP_STATUS=OK\nVIVADO_MCP_SOURCE={source.as_posix()}\n"
            "VIVADO_MCP_FILESET=sim_1\n"
        )
    )
    result = SourceManager(fake).add_source(
        str(tmp_path), str(source), fileset="sim_1"
    )
    assert result.success is True
    assert "add_files -fileset sim_1 -norecurse" in fake.scripts[0]
    assert "update_compile_order -fileset sim_1" in fake.scripts[0]


def test_add_source_missing_file(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = SourceManager(FakeVivado()).add_source(
        str(tmp_path), str(tmp_path / "missing.v")
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "SourceNotFoundError"


def test_remove_source_keeps_file(tmp_path: Path) -> None:
    _make_project(tmp_path)
    source = tmp_path / "counter.v"
    source.write_text("module counter; endmodule\n", encoding="utf-8")
    fake = FakeVivado(
        stdout=(
            f"VIVADO_MCP_STATUS=OK\nVIVADO_MCP_SOURCE={source.as_posix()}\n"
            "VIVADO_MCP_REMOVED=1\n"
        )
    )
    result = SourceManager(fake).remove_source(str(tmp_path), str(source))
    assert result.success is True
    assert source.exists()
    assert "remove_files" in fake.scripts[0]


def test_remove_source_not_in_project(tmp_path: Path) -> None:
    _make_project(tmp_path)
    source = tmp_path / "counter.v"
    source.write_text("module counter; endmodule\n", encoding="utf-8")
    fake = FakeVivado(
        fail=True,
        stdout="VIVADO_MCP_STATUS=ERROR\nVIVADO_MCP_ERROR=SOURCE_NOT_IN_PROJECT\n",
    )
    result = SourceManager(fake).remove_source(str(tmp_path), str(source))
    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "SourceNotFoundError"


def test_list_sources_parsing() -> None:
    stdout = """
VIVADO_MCP_SOURCE_PATH=/tmp/proj/rtl/counter.v
VIVADO_MCP_SOURCE_TYPE=Verilog
VIVADO_MCP_SOURCE_LIBRARY=xil_defaultlib
VIVADO_MCP_SOURCE_END=1
VIVADO_MCP_SOURCE_PATH=/tmp/proj/rtl/top.sv
VIVADO_MCP_SOURCE_TYPE=SystemVerilog
VIVADO_MCP_SOURCE_LIBRARY=xil_defaultlib
VIVADO_MCP_SOURCE_END=1
VIVADO_MCP_STATUS=OK
"""
    sources = parse_source_list(stdout)
    assert len(sources) == 2
    assert sources[0].type == "verilog"
    assert sources[0].library == "xil_defaultlib"
    assert sources[1].type == "systemverilog"


def test_list_sources_tool(tmp_path: Path) -> None:
    _make_project(tmp_path)
    fake = FakeVivado(
        stdout=(
            f"VIVADO_MCP_SOURCE_PATH={(tmp_path / 'rtl' / 'counter.v').as_posix()}\n"
            "VIVADO_MCP_SOURCE_TYPE=Verilog\n"
            "VIVADO_MCP_SOURCE_LIBRARY=xil_defaultlib\n"
            "VIVADO_MCP_SOURCE_END=1\n"
            "VIVADO_MCP_STATUS=OK\n"
        )
    )
    result = SourceManager(fake).list_sources(str(tmp_path))
    assert result.success is True
    assert result.sources is not None
    assert len(result.sources) == 1
    assert "get_filesets sources_1" in fake.scripts[0]


def test_tcl_builders_quote_spaces() -> None:
    xpr = Path(r"C:\Users\User Name\proj\demo.xpr")
    source = Path(r"C:\Users\User Name\proj\rtl\counter.v")
    add_script = build_add_source_tcl(xpr_path=xpr, source_path=source)
    remove_script = build_remove_source_tcl(xpr_path=xpr, source_path=source)
    list_script = build_list_sources_tcl(xpr_path=xpr)
    assert "User Name" in add_script
    assert "add_files -norecurse" in add_script
    assert "remove_files" in remove_script
    assert "SOURCE_NOT_IN_PROJECT" in remove_script
    assert "SOURCE_PATH" in list_script


def test_language_from_path() -> None:
    assert language_from_path(Path("a.v")) == "verilog"
    assert language_from_path(Path("a.sv")) == "systemverilog"
    with pytest.raises(InvalidSourceError):
        language_from_path(Path("a.vhdl"))


def test_add_source_vivado_failure(tmp_path: Path) -> None:
    _make_project(tmp_path)
    source = tmp_path / "counter.v"
    source.write_text("module counter; endmodule\n", encoding="utf-8")
    result = SourceManager(FakeVivado(fail=True)).add_source(str(tmp_path), str(source))
    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "VivadoExecutionError"
