"""Unit tests for RTL simulation management (no real Vivado required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vivado_mcp.config import Config
from vivado_mcp.errors import (
    InvalidSimulationTimeError,
    InvalidTopModuleError,
)
from vivado_mcp.simulation import (
    STATUS_ASSERTION_FAILED,
    STATUS_COMPILE_ERROR,
    STATUS_COMPLETED,
    STATUS_ELABORATE_ERROR,
    STATUS_NOT_RUN,
    STATUS_PASSED,
    SimulationManager,
    classify_simulation_status,
    parse_simulation_output,
)
from vivado_mcp.tcl import (
    build_run_simulation_tcl,
    validate_simulation_time,
    validate_top_module,
)
from vivado_mcp.vivado import CommandResult, Vivado, VivadoVersionInfo


def _make_project(tmp_path: Path, name: str = "demo") -> Path:
    xpr = tmp_path / f"{name}.xpr"
    xpr.write_text(f"# fake {name}\n", encoding="utf-8")
    return xpr


class FakeVivado(Vivado):
    def __init__(self, *, fail: bool = False, stdout: str = "", stderr: str = "") -> None:
        super().__init__(Config(), platform_name="Linux")
        self.fail = fail
        self.stdout = stdout
        self.stderr = stderr
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
                stderr=self.stderr or "ERROR: simulated",
            )
        return CommandResult(
            returncode=0,
            stdout=self.stdout
            or (
                "VIVADO_MCP_STATUS=OK\n"
                "VIVADO_MCP_SIM_STATUS=passed\n"
                "VIVADO_MCP_SIM_TOP=counter_tb\n"
                "VIVADO_MCP_SIM_TIME=100ns\n"
            ),
            stderr="",
            args=("vivado",),
        )


def test_validate_simulation_time_accepts_common_formats() -> None:
    assert validate_simulation_time("100ns") == "100ns"
    assert validate_simulation_time("10NS") == "10ns"
    assert validate_simulation_time("1us") == "1us"
    assert validate_simulation_time("1.5ms") == "1.5ms"
    assert validate_simulation_time("2s") == "2s"


def test_validate_simulation_time_rejects_tcl_and_junk() -> None:
    with pytest.raises(InvalidSimulationTimeError):
        validate_simulation_time("")
    with pytest.raises(InvalidSimulationTimeError):
        validate_simulation_time("100 ns")
    with pytest.raises(InvalidSimulationTimeError):
        validate_simulation_time("100ns; exit")
    with pytest.raises(InvalidSimulationTimeError):
        validate_simulation_time("[exec rm -rf /]")
    with pytest.raises(InvalidSimulationTimeError):
        validate_simulation_time("forever")


def test_validate_top_module() -> None:
    assert validate_top_module("counter_tb") == "counter_tb"
    with pytest.raises(InvalidTopModuleError):
        validate_top_module("")
    with pytest.raises(InvalidTopModuleError):
        validate_top_module("bad top")
    with pytest.raises(InvalidTopModuleError):
        validate_top_module("tb;puts hi")


def test_create_testbench_verilog_and_systemverilog(tmp_path: Path) -> None:
    _make_project(tmp_path)
    manager = SimulationManager(FakeVivado())

    v_result = manager.create_testbench(
        project_path=str(tmp_path),
        filename="counter_tb",
        code="module counter_tb; endmodule\n",
        language="verilog",
    )
    assert v_result.success is True
    assert v_result.file is not None
    assert v_result.file.type == "testbench"
    assert v_result.file.language == "verilog"
    assert Path(v_result.file.path) == tmp_path / "sim" / "counter_tb.v"
    assert Path(v_result.file.path).read_text(encoding="utf-8") == (
        "module counter_tb; endmodule\n"
    )

    sv_result = manager.create_testbench(
        project_path=str(tmp_path),
        filename="tb.sv",
        code="module tb; endmodule\n",
        language="systemverilog",
    )
    assert sv_result.success is True
    assert sv_result.file is not None
    assert sv_result.file.language == "systemverilog"
    assert Path(sv_result.file.path) == tmp_path / "sim" / "tb.sv"


def test_create_testbench_rejects_existing_and_traversal(tmp_path: Path) -> None:
    _make_project(tmp_path)
    manager = SimulationManager(FakeVivado())
    first = manager.create_testbench(
        str(tmp_path), "tb.v", "module tb; endmodule\n", "verilog"
    )
    assert first.success is True
    second = manager.create_testbench(
        str(tmp_path), "tb.v", "module other; endmodule\n", "verilog"
    )
    assert second.success is False
    assert second.error is not None
    assert second.error["type"] == "SourceAlreadyExistsError"

    bad = manager.create_testbench(
        str(tmp_path), "../escape.v", "module x; endmodule\n", "verilog"
    )
    assert bad.success is False
    assert bad.error is not None
    assert bad.error["type"] == "InvalidSourceError"

    bad_ext = manager.create_testbench(
        str(tmp_path), "tb.vhdl", "entity tb; end;\n", "verilog"
    )
    assert bad_ext.success is False


def test_create_testbench_does_not_call_vivado(tmp_path: Path) -> None:
    _make_project(tmp_path)
    fake = FakeVivado()
    SimulationManager(fake).create_testbench(
        str(tmp_path), "tb.v", "module tb; endmodule\n", "verilog"
    )
    assert fake.scripts == []


def test_run_simulation_success(tmp_path: Path) -> None:
    _make_project(tmp_path)
    fake = FakeVivado(
        stdout=(
            "VIVADO_MCP_SIM_TOP=counter_tb\n"
            "VIVADO_MCP_SIM_TIME=100ns\n"
            "NOTE: Simulation completed\n"
            "VIVADO_MCP_STATUS=OK\n"
            "VIVADO_MCP_SIM_STATUS=passed\n"
        )
    )
    result = SimulationManager(fake).run_simulation(
        str(tmp_path), top_module="counter_tb", simulation_time="100ns"
    )
    assert result.success is True
    assert result.status == STATUS_COMPLETED
    assert result.top_module == "counter_tb"
    assert result.simulation_time == "100ns"
    assert result.vivado_version == "2018.2"
    assert "launch_simulation -mode behavioral" in fake.scripts[0]
    assert "xsim.simulate.runtime" in fake.scripts[0]
    assert "close_project" in fake.scripts[0]
    status = SimulationManager(fake).get_simulation_status(str(tmp_path))
    assert status.ran is True
    assert status.status == STATUS_COMPLETED


def test_run_simulation_rejects_bad_time(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = SimulationManager(FakeVivado()).run_simulation(
        str(tmp_path), simulation_time="100ns; puts pwned"
    )
    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "InvalidSimulationTimeError"


def test_run_simulation_compile_error(tmp_path: Path) -> None:
    _make_project(tmp_path)
    fake = FakeVivado(
        fail=True,
        stdout=(
            "ERROR: [VRFC 10-91] syntax error near 'endmodule'\n"
            "VIVADO_MCP_STATUS=ERROR\n"
            "VIVADO_MCP_SIM_STATUS=failed\n"
            "VIVADO_MCP_SIM_ERROR=launch failed\n"
        ),
        stderr="ERROR: [VRFC 10-91] syntax error\n",
    )
    result = SimulationManager(fake).run_simulation(str(tmp_path), top_module="tb")
    assert result.success is False
    assert result.status == STATUS_COMPILE_ERROR
    assert result.error is not None


def test_run_simulation_no_sources(tmp_path: Path) -> None:
    _make_project(tmp_path)
    fake = FakeVivado(
        fail=True,
        stdout=(
            "VIVADO_MCP_STATUS=ERROR\n"
            "VIVADO_MCP_SIM_STATUS=no_sources\n"
            "VIVADO_MCP_SIM_ERROR=No simulation sources in fileset sim_1\n"
        ),
    )
    result = SimulationManager(fake).run_simulation(str(tmp_path))
    assert result.success is False
    assert result.error is not None
    assert result.error["type"] == "NoSimulationSourcesError"


def test_get_simulation_status_not_run(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = SimulationManager(FakeVivado()).get_simulation_status(str(tmp_path))
    assert result.success is True
    assert result.status == STATUS_NOT_RUN
    assert result.ran is False


def test_classify_compile_elaborate_assertion() -> None:
    assert (
        classify_simulation_status("ERROR: [VRFC 10-1] syntax error near foo")
        == STATUS_COMPILE_ERROR
    )
    assert (
        classify_simulation_status("ERROR: Static elaboration of top level failed")
        == STATUS_ELABORATE_ERROR
    )
    assert (
        classify_simulation_status("Error: Assertion failed at time 50ns")
        == STATUS_ASSERTION_FAILED
    )
    assert (
        classify_simulation_status(
            "VIVADO_MCP_STATUS=OK\nVIVADO_MCP_SIM_STATUS=passed\n"
        )
        == STATUS_PASSED
    )


def test_classify_ignores_vrfc_warning_when_marker_passed() -> None:
    """Regression: Vivado 2018.2 timescale WARNING must not override a pass."""
    log = (
        "WARNING: [VRFC 10-2263] Module counter has no timescale\n"
        "MCP_SIM_PASS\n"
        "$finish called at time : 96 ns\n"
        "VIVADO_MCP_STATUS=OK\n"
        "VIVADO_MCP_SIM_STATUS=passed\n"
        "VIVADO_MCP_SIM_TOP=counter_tb\n"
    )
    assert classify_simulation_status(log, marker_status="passed") == STATUS_PASSED
    parsed = parse_simulation_output(log)
    assert parsed.status == STATUS_PASSED
    assert parsed.errors == 0
    assert parsed.warnings >= 1


def test_classify_vrfc_warning_alone_is_not_compile_error() -> None:
    assert (
        classify_simulation_status(
            "WARNING: [VRFC 10-2263] Module counter has no timescale\n"
        )
        != STATUS_COMPILE_ERROR
    )


def test_parse_simulation_output_counts() -> None:
    stdout = (
        "WARNING: [VRFC] unused signal\n"
        "WARNING: something\n"
        "ERROR: [VRFC 10-91] syntax error\n"
        "VIVADO_MCP_SIM_STATUS=failed\n"
    )
    parsed = parse_simulation_output(stdout)
    assert parsed.status == STATUS_COMPILE_ERROR
    assert parsed.errors >= 1
    assert parsed.warnings >= 1


def test_build_run_simulation_tcl_quotes_and_validates() -> None:
    xpr = Path(r"C:\Users\User Name\proj\demo.xpr")
    script = build_run_simulation_tcl(
        xpr_path=xpr,
        simulation_time="100ns",
        top_module="counter_tb",
    )
    assert "User Name" in script
    assert "launch_simulation -mode behavioral" in script
    assert "set_property top {counter_tb}" in script
    assert "xsim.simulate.runtime" in script
    assert "100ns" in script
    assert "close_sim" in script
    assert "close_project" in script
    with pytest.raises(InvalidSimulationTimeError):
        build_run_simulation_tcl(xpr_path=xpr, simulation_time="bad")
