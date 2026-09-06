"""Integration tests for synthesis (requires Vivado)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from vivado_mcp.config import Config
from vivado_mcp.projects import ProjectManager
from vivado_mcp.sources import SourceManager
from vivado_mcp.synthesis import (
    STATUS_AVAILABLE,
    STATUS_COMPLETED,
    STATUS_NOT_AVAILABLE,
    SynthesisManager,
)
from vivado_mcp.vivado import Vivado

COUNTER_RTL = """\
module counter(
  input wire clk,
  input wire rst,
  output reg [3:0] count
);
  always @(posedge clk) begin
    if (rst)
      count <= 4'b0000;
    else
      count <= count + 1'b1;
  end
endmodule
"""


def _vivado_available() -> bool:
    try:
        info = Vivado(Config.from_env()).get_version()
    except Exception:
        return False
    return bool(info.installed)


def _cleanup_project_tree(parent: Path, name: str) -> None:
    shutil.rmtree(parent / name, ignore_errors=True)
    for leftover in parent.glob(f"{name}*"):
        if leftover.is_dir():
            shutil.rmtree(leftover, ignore_errors=True)
        else:
            leftover.unlink(missing_ok=True)
    for folder in ("rtl", "sim", ".vivado_mcp"):
        shutil.rmtree(parent / folder, ignore_errors=True)


@pytest.mark.integration
def test_real_vivado_synthesis_workflow(tmp_path: Path) -> None:
    if not _vivado_available():
        pytest.skip("Vivado is not installed on this machine")

    vivado = Vivado(Config.from_env())
    projects = ProjectManager(vivado)
    sources = SourceManager(vivado)
    synthesis = SynthesisManager(vivado)

    parent = tmp_path / "vivado_mcp_synth_it"
    parent.mkdir()

    created = projects.create_project(
        name="synth_demo",
        path=str(parent),
        part="xc7a35tcpg236-1",
    )
    assert created.success is True, created.error
    assert created.project is not None
    project_path = created.project.xpr or created.project.path

    rtl = sources.create_rtl_file(
        project_path=str(project_path),
        filename="counter.v",
        code=COUNTER_RTL,
        language="verilog",
    )
    assert rtl.success is True, rtl.error
    assert rtl.source_path is not None

    added = sources.add_source(
        str(project_path), rtl.source_path, fileset="sources_1"
    )
    assert added.success is True, added.error

    before = synthesis.get_utilization(str(project_path))
    assert before.status == STATUS_NOT_AVAILABLE

    synth = synthesis.run_synthesis(str(project_path))
    assert synth.success is True, (synth.error, synth.log_summary)
    assert synth.status == STATUS_COMPLETED

    util = synthesis.get_utilization(str(project_path))
    assert util.success is True, util.error
    assert util.status == STATUS_AVAILABLE
    assert util.resources is not None
    # At least one resource field should parse on Artix-7.
    assert any(value is not None for value in util.resources.values())

    timing = synthesis.get_timing(str(project_path))
    assert timing.success is True, timing.error
    # Without XDC, timing may be not_available — that is acceptable.
    assert timing.status in {STATUS_AVAILABLE, STATUS_NOT_AVAILABLE}
    if timing.status == STATUS_AVAILABLE:
        assert timing.timing is not None

    _cleanup_project_tree(parent, "synth_demo")
