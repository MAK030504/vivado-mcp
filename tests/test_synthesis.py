"""Unit tests for synthesis management (no real Vivado required)."""

from __future__ import annotations

from pathlib import Path

from vivado_mcp.config import Config
from vivado_mcp.synthesis import (
    STATUS_AVAILABLE,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_NOT_AVAILABLE,
    SynthesisManager,
)
from vivado_mcp.tcl import build_run_synthesis_tcl
from vivado_mcp.vivado import CommandResult, Vivado, VivadoVersionInfo

UTIL_SNIPPET = """
| Site Type | Used | Fixed | Available | Util% |
| Slice LUTs | 12 | 0 | 20800 | 0.06 |
| Slice Registers | 8 | 0 | 41600 | 0.02 |
| Block RAM Tile | 0 | 0 | 50 | 0.00 |
| DSPs | 0 | 0 | 90 | 0.00 |
| Bonded IOB | 3 | 0 | 106 | 2.83 |
| BUFGCTRL | 1 | 0 | 32 | 3.13 |
"""

TIMING_SNIPPET = """
    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints
    -------      -------  ---------------------  -------------------
      1.420        0.000                      0                 100

All user specified timing constraints are met.
"""


def _make_project(tmp_path: Path, name: str = "demo") -> Path:
    xpr = tmp_path / f"{name}.xpr"
    xpr.write_text(f"# fake {name}\n", encoding="utf-8")
    return xpr


class FakeVivado(Vivado):
    def __init__(
        self,
        *,
        fail: bool = False,
        stdout: str = "",
        stderr: str = "",
        write_reports: bool = False,
        report_dir_hint: Path | None = None,
    ) -> None:
        super().__init__(Config(), platform_name="Linux")
        self.fail = fail
        self.stdout = stdout
        self.stderr = stderr
        self.write_reports = write_reports
        self.report_dir_hint = report_dir_hint
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
        if self.write_reports and self.report_dir_hint is not None:
            self.report_dir_hint.mkdir(parents=True, exist_ok=True)
            (self.report_dir_hint / "utilization.rpt").write_text(
                UTIL_SNIPPET, encoding="utf-8"
            )
            (self.report_dir_hint / "timing_summary.rpt").write_text(
                TIMING_SNIPPET, encoding="utf-8"
            )
        if self.fail:
            from vivado_mcp.errors import VivadoExecutionError

            raise VivadoExecutionError(
                "simulated vivado failure",
                returncode=1,
                stdout=self.stdout or "VIVADO_MCP_STATUS=ERROR\n",
                stderr=self.stderr or "ERROR: [Synth 8-27] failed\n",
            )
        return CommandResult(
            returncode=0,
            stdout=self.stdout
            or (
                "VIVADO_MCP_STATUS=OK\n"
                "VIVADO_MCP_SYNTH_STATUS=completed\n"
                "VIVADO_MCP_SYNTH_TOP=counter\n"
                "VIVADO_MCP_SYNTH_RUN_STATUS=synth_design Complete!\n"
            ),
            stderr="",
            args=("vivado",),
        )


def test_build_run_synthesis_tcl_quotes_and_is_batch_safe() -> None:
    xpr = Path(r"C:\Users\User Name\proj\demo.xpr")
    report_dir = Path(r"C:\Users\User Name\proj\.vivado_mcp\reports")
    script = build_run_synthesis_tcl(xpr_path=xpr, report_dir=report_dir)
    assert "User Name" in script
    assert "launch_runs synth_1" in script
    assert "wait_on_run synth_1" in script
    assert "report_utilization" in script
    assert "report_timing_summary" in script
    assert "start_gui" not in script
    assert "close_project" in script


def test_run_synthesis_success(tmp_path: Path) -> None:
    _make_project(tmp_path)
    report_dir = tmp_path / ".vivado_mcp" / "reports"
    fake = FakeVivado(write_reports=True, report_dir_hint=report_dir)
    result = SynthesisManager(fake).run_synthesis(str(tmp_path))
    assert result.success is True
    assert result.status == STATUS_COMPLETED
    assert result.top_module == "counter"
    assert result.vivado_version == "2018.2"
    assert "launch_runs synth_1" in fake.scripts[0]


def test_run_synthesis_failure(tmp_path: Path) -> None:
    _make_project(tmp_path)
    fake = FakeVivado(
        fail=True,
        stdout=(
            "ERROR: [Synth 8-27] synth failed\n"
            "VIVADO_MCP_STATUS=ERROR\n"
            "VIVADO_MCP_SYNTH_STATUS=failed\n"
            "VIVADO_MCP_SYNTH_ERROR=Synthesis run did not complete\n"
            "VIVADO_MCP_SYNTH_RUN_STATUS=synth_design ERROR\n"
        ),
        stderr="ERROR: [Synth 8-27] synth failed\n",
    )
    result = SynthesisManager(fake).run_synthesis(str(tmp_path))
    assert result.success is False
    assert result.status == STATUS_FAILED
    assert result.errors is not None
    assert result.error is not None


def test_get_utilization_not_available_before_synth(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = SynthesisManager(FakeVivado()).get_utilization(str(tmp_path))
    assert result.success is True
    assert result.status == STATUS_NOT_AVAILABLE
    assert result.reason is not None


def test_get_utilization_after_synth(tmp_path: Path) -> None:
    _make_project(tmp_path)
    report_dir = tmp_path / ".vivado_mcp" / "reports"
    fake = FakeVivado(write_reports=True, report_dir_hint=report_dir)
    synth = SynthesisManager(fake).run_synthesis(str(tmp_path))
    assert synth.success is True
    util = SynthesisManager(fake).get_utilization(str(tmp_path))
    assert util.success is True
    assert util.status == STATUS_AVAILABLE
    assert util.resources is not None
    assert util.resources["lut"] is not None
    assert util.resources["lut"]["used"] == 12
    assert util.resources["ff"] is not None


def test_get_timing_after_synth(tmp_path: Path) -> None:
    _make_project(tmp_path)
    report_dir = tmp_path / ".vivado_mcp" / "reports"
    fake = FakeVivado(write_reports=True, report_dir_hint=report_dir)
    assert SynthesisManager(fake).run_synthesis(str(tmp_path)).success is True
    timing = SynthesisManager(fake).get_timing(str(tmp_path))
    assert timing.success is True
    assert timing.status == STATUS_AVAILABLE
    assert timing.timing is not None
    assert timing.timing["wns_ns"] == 1.42
    assert timing.timing["status"] == "met"


def test_get_timing_not_available_without_synth(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = SynthesisManager(FakeVivado()).get_timing(str(tmp_path))
    assert result.success is True
    assert result.status == STATUS_NOT_AVAILABLE


def test_invalid_project_path() -> None:
    result = SynthesisManager(FakeVivado()).run_synthesis("/no/such/project.xpr")
    assert result.success is False
    assert result.error is not None
