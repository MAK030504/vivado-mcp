"""Integration tests for RTL simulation (requires Vivado)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from vivado_mcp.config import Config
from vivado_mcp.projects import ProjectManager
from vivado_mcp.simulation import STATUS_COMPLETED, STATUS_NOT_RUN, SimulationManager
from vivado_mcp.sources import SourceManager
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

COUNTER_TB = """\
`timescale 1ns/1ps
module counter_tb;
  reg clk;
  reg rst;
  wire [3:0] count;

  counter dut (
    .clk(clk),
    .rst(rst),
    .count(count)
  );

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  initial begin
    rst = 1'b1;
    #20;
    rst = 1'b0;
    #80;
    $display("MCP_SIM_RESULT count=%0d", count);
    $display("MCP_SIM_PASS");
    $finish;
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
def test_real_vivado_simulation_workflow(tmp_path: Path) -> None:
    if not _vivado_available():
        pytest.skip("Vivado is not installed on this machine")

    vivado = Vivado(Config.from_env())
    projects = ProjectManager(vivado)
    sources = SourceManager(vivado)
    simulation = SimulationManager(vivado)

    parent = tmp_path / "vivado_mcp_sim_it"
    parent.mkdir()

    created = projects.create_project(
        name="sim_demo",
        path=str(parent),
        part="xc7a35tcpg236-1",
    )
    assert created.success is True, created.error
    assert created.project is not None
    project_path = created.project.xpr or created.project.path

    status_before = simulation.get_simulation_status(str(project_path))
    assert status_before.status == STATUS_NOT_RUN
    assert status_before.ran is False

    rtl = sources.create_rtl_file(
        project_path=str(project_path),
        filename="counter.v",
        code=COUNTER_RTL,
        language="verilog",
    )
    assert rtl.success is True, rtl.error
    assert rtl.source_path is not None

    tb = simulation.create_testbench(
        project_path=str(project_path),
        filename="counter_tb.v",
        code=COUNTER_TB,
        language="verilog",
    )
    assert tb.success is True, tb.error
    assert tb.file is not None
    tb_path = Path(tb.file.path)
    assert tb_path.exists()

    added_rtl = sources.add_source(
        str(project_path), rtl.source_path, fileset="sources_1"
    )
    assert added_rtl.success is True, added_rtl.error

    added_tb = sources.add_source(str(project_path), str(tb_path), fileset="sim_1")
    assert added_tb.success is True, added_tb.error

    sim = simulation.run_simulation(
        project_path=str(project_path),
        top_module="counter_tb",
        simulation_time="100ns",
    )
    assert sim.success is True, (sim.error, sim.output)
    assert sim.status in {STATUS_COMPLETED, "passed"}
    assert sim.top_module == "counter_tb"
    assert sim.simulation_time == "100ns"
    assert sim.output is not None
    assert "MCP_SIM_PASS" in sim.output or "MCP_SIM_RESULT" in sim.output

    status = simulation.get_simulation_status(str(project_path))
    assert status.ran is True
    assert status.success is True
    assert status.top_module == "counter_tb"

    _cleanup_project_tree(parent, "sim_demo")
