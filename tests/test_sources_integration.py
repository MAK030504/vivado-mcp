"""Integration tests for RTL source management (requires Vivado)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from vivado_mcp.config import Config
from vivado_mcp.projects import ProjectManager
from vivado_mcp.sources import SourceManager
from vivado_mcp.vivado import Vivado


def _vivado_available() -> bool:
    try:
        info = Vivado(Config.from_env()).get_version()
    except Exception:
        return False
    return bool(info.installed)


@pytest.mark.integration
def test_real_vivado_rtl_source_workflow(tmp_path: Path) -> None:
    if not _vivado_available():
        pytest.skip("Vivado is not installed on this machine")

    vivado = Vivado(Config.from_env())
    projects = ProjectManager(vivado)
    sources = SourceManager(vivado)

    parent = tmp_path / "vivado_mcp_rtl_it"
    parent.mkdir()

    created = projects.create_project(
        name="rtl_demo",
        path=str(parent),
        part="xc7a35tcpg236-1",
    )
    assert created.success is True, created.error
    assert created.project is not None
    project_path = created.project.xpr or created.project.path

    rtl = sources.create_rtl_file(
        project_path=str(project_path),
        filename="counter.v",
        code=(
            "module counter(\n"
            "  input wire clk,\n"
            "  output reg [3:0] q\n"
            ");\n"
            "  always @(posedge clk) q <= q + 1'b1;\n"
            "endmodule\n"
        ),
        language="verilog",
    )
    assert rtl.success is True, rtl.error
    assert rtl.source_path is not None
    rtl_path = Path(rtl.source_path)
    assert rtl_path.exists()

    added = sources.add_source(str(project_path), str(rtl_path))
    assert added.success is True, added.error

    listed = sources.list_sources(str(project_path))
    assert listed.success is True, listed.error
    assert listed.sources is not None
    assert any(Path(item.path).name == "counter.v" for item in listed.sources)

    removed = sources.remove_source(str(project_path), str(rtl_path))
    assert removed.success is True, removed.error
    assert rtl_path.exists()

    listed_after = sources.list_sources(str(project_path))
    assert listed_after.success is True, listed_after.error
    assert listed_after.sources is not None
    assert not any(Path(item.path).name == "counter.v" for item in listed_after.sources)

    shutil.rmtree(parent / "rtl_demo", ignore_errors=True)
    # Also clean flat layout used by some Vivado versions.
    for leftover in parent.glob("rtl_demo*"):
        if leftover.is_dir():
            shutil.rmtree(leftover, ignore_errors=True)
        else:
            leftover.unlink(missing_ok=True)
    shutil.rmtree(parent / "rtl", ignore_errors=True)
