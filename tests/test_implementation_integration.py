"""Integration tests for implementation (requires Vivado)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from vivado_mcp.config import Config
from vivado_mcp.implementation import (
    STATUS_AVAILABLE,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_NOT_AVAILABLE,
    ImplementationManager,
)
from vivado_mcp.projects import ProjectManager
from vivado_mcp.sources import SourceManager
from vivado_mcp.synthesis import STATUS_COMPLETED as SYNTH_COMPLETED
from vivado_mcp.synthesis import SynthesisManager
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
def test_real_vivado_implementation_workflow(tmp_path: Path) -> None:
    """Temporary counter project: synth → implement → reports → cleanup.

    Does not modify any permanent project such as mcp_counter.
    """
    if not _vivado_available():
        pytest.skip("Vivado is not installed on this machine")

    vivado = Vivado(Config.from_env())
    projects = ProjectManager(vivado)
    sources = SourceManager(vivado)
    synthesis = SynthesisManager(vivado)
    implementation = ImplementationManager(vivado)

    parent = tmp_path / "vivado_mcp_impl_it"
    parent.mkdir()
    project_name = "impl_demo"

    try:
        created = projects.create_project(
            name=project_name,
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
            project_path=str(project_path),
            source_path=rtl.source_path,
            fileset="sources_1",
        )
        assert added.success is True, added.error

        blocked = implementation.run_implementation(str(project_path))
        assert blocked.success is False
        assert blocked.status == STATUS_BLOCKED
        assert "Synthesis must complete" in (blocked.reason or blocked.message or "")

        synth = synthesis.run_synthesis(str(project_path))
        assert synth.success is True, (synth.error, synth.log_summary)
        assert synth.status == SYNTH_COMPLETED

        impl = implementation.run_implementation(str(project_path))
        assert impl.success is True, (impl.error, impl.log_summary, impl.failure_kind)
        assert impl.status == STATUS_COMPLETED

        status = implementation.get_implementation_status(str(project_path))
        assert status.success is True
        assert status.status == STATUS_COMPLETED

        util = implementation.get_implemented_utilization(str(project_path))
        assert util.success is True, util.error
        assert util.status == STATUS_AVAILABLE
        assert util.stage == "implementation"
        assert util.resources is not None
        assert any(value is not None for value in util.resources.values())

        timing = implementation.get_timing(str(project_path))
        assert timing.success is True, timing.error
        assert timing.stage == "implementation"
        # Without XDC, timing is often not_available — that is expected.
        assert timing.status in {STATUS_AVAILABLE, STATUS_NOT_AVAILABLE}
        if timing.status == STATUS_AVAILABLE:
            assert timing.timing is not None
            assert "wns_ns" in timing.timing
        else:
            assert timing.reason is not None
    finally:
        _cleanup_project_tree(parent, project_name)
