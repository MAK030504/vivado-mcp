"""Unit tests for implementation management (no real Vivado required)."""

from __future__ import annotations

from pathlib import Path

from vivado_mcp.config import Config
from vivado_mcp.errors import VivadoExecutionError
from vivado_mcp.implementation import (
    STATUS_AVAILABLE,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_NOT_AVAILABLE,
    STATUS_NOT_STARTED,
    STATUS_TIMEOUT,
    ImplementationManager,
)
from vivado_mcp.reports import (
    VivadoReportParser,
    classify_impl_failure,
    classify_impl_run_status,
)
from vivado_mcp.tcl import build_run_implementation_tcl
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

TIMING_MET = """
    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints
    -------      -------  ---------------------  -------------------
      1.240        0.000                      0                 100

All user specified timing constraints are met.
"""

TIMING_FAIL = """
    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints
    -------      -------  ---------------------  -------------------
     -0.420       -3.210                      4                 100

Timing constraints are not met.
"""

NO_CONSTRAINTS = """
No user specified timing constraints were found for this design.
"""


def _make_project(tmp_path: Path, name: str = "demo") -> Path:
    xpr = tmp_path / f"{name}.xpr"
    xpr.write_text(f"# fake {name}\n", encoding="utf-8")
    return xpr


class FakeVivado(Vivado):
    def __init__(
        self,
        *,
        mode: str = "success",
        stdout: str = "",
        stderr: str = "",
        report_dir_hint: Path | None = None,
    ) -> None:
        super().__init__(Config(), platform_name="Linux")
        self.mode = mode
        self.stdout = stdout
        self.stderr = stderr
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

        if "launch_runs impl_1" in script:
            return self._handle_run()

        if "report_utilization" in script and "impl_1" in script:
            self._write_util()
            return CommandResult(
                returncode=0,
                stdout="VIVADO_MCP_STATUS=OK\n",
                stderr="",
                args=("vivado",),
            )

        if "report_timing_summary" in script and "impl_1" in script:
            self._write_timing(TIMING_MET)
            return CommandResult(
                returncode=0,
                stdout="VIVADO_MCP_STATUS=OK\nVIVADO_MCP_TIMING_STATUS=available\n",
                stderr="",
                args=("vivado",),
            )

        return CommandResult(
            returncode=0,
            stdout=(
                self.stdout
                or (
                    "VIVADO_MCP_STATUS=OK\n"
                    "VIVADO_MCP_IMPL_STATUS=not_started\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=\n"
                )
            ),
            stderr="",
            args=("vivado",),
        )

    def _write_util(self) -> None:
        if self.report_dir_hint is None:
            return
        self.report_dir_hint.mkdir(parents=True, exist_ok=True)
        (self.report_dir_hint / "impl_utilization.rpt").write_text(
            UTIL_SNIPPET, encoding="utf-8"
        )

    def _write_timing(self, text: str) -> None:
        if self.report_dir_hint is None:
            return
        self.report_dir_hint.mkdir(parents=True, exist_ok=True)
        (self.report_dir_hint / "impl_timing_summary.rpt").write_text(
            text, encoding="utf-8"
        )

    def _handle_run(self) -> CommandResult:
        if self.mode == "blocked":
            raise VivadoExecutionError(
                "simulated blocked implementation",
                returncode=1,
                stdout=(
                    "VIVADO_MCP_STATUS=ERROR\n"
                    "VIVADO_MCP_IMPL_STATUS=blocked\n"
                    "VIVADO_MCP_IMPL_ERROR="
                    "Synthesis must complete before implementation\n"
                ),
                stderr="",
            )
        if self.mode == "timeout":
            raise VivadoExecutionError(
                "Vivado timed out after 7200 seconds.",
                returncode=None,
                stdout="",
                stderr="",
            )
        if self.mode == "place_fail":
            raise VivadoExecutionError(
                "simulated placement failure",
                returncode=1,
                stdout=(
                    "VIVADO_MCP_STATUS=ERROR\n"
                    "VIVADO_MCP_IMPL_STATUS=failed\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=place_design ERROR\n"
                    "VIVADO_MCP_IMPL_ERROR=place_design failed\n"
                ),
                stderr="ERROR: [Place 30-99] Failed to place\n",
            )
        if self.mode == "route_fail":
            raise VivadoExecutionError(
                "simulated routing failure",
                returncode=1,
                stdout=(
                    "VIVADO_MCP_STATUS=ERROR\n"
                    "VIVADO_MCP_IMPL_STATUS=failed\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=route_design ERROR\n"
                    "VIVADO_MCP_IMPL_ERROR=route_design failed\n"
                ),
                stderr="ERROR: [Route 35-39] Router failed\n",
            )

        self._write_util()
        if self.mode == "no_timing":
            self._write_timing(NO_CONSTRAINTS)
            timing_status = "not_available"
        elif self.mode == "timing_fail":
            self._write_timing(TIMING_FAIL)
            timing_status = "available"
        else:
            self._write_timing(TIMING_MET)
            timing_status = "available"

        return CommandResult(
            returncode=0,
            stdout=(
                self.stdout
                or (
                    "VIVADO_MCP_STATUS=OK\n"
                    "VIVADO_MCP_IMPL_STATUS=completed\n"
                    "VIVADO_MCP_IMPL_TOP=counter\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=route_design Complete!\n"
                    f"VIVADO_MCP_TIMING_STATUS={timing_status}\n"
                )
            ),
            stderr="",
            args=("vivado",),
        )


def test_build_run_implementation_tcl_quotes_and_is_batch_safe() -> None:
    xpr = Path(r"C:\Users\User Name\proj\demo.xpr")
    report_dir = Path(r"C:\Users\User Name\proj\.vivado_mcp\reports")
    script = build_run_implementation_tcl(xpr_path=xpr, report_dir=report_dir)
    assert "User Name" in script
    assert "launch_runs impl_1" in script
    assert "wait_on_run impl_1" in script
    assert "Synthesis must complete before implementation" in script
    assert "report_utilization" in script
    assert "report_timing_summary" in script
    assert "start_gui" not in script
    assert "close_project" in script


def test_run_implementation_success(tmp_path: Path) -> None:
    _make_project(tmp_path)
    report_dir = tmp_path / ".vivado_mcp" / "reports"
    fake = FakeVivado(mode="success", report_dir_hint=report_dir)
    result = ImplementationManager(fake).run_implementation(str(tmp_path))
    assert result.success is True
    assert result.status == STATUS_COMPLETED
    assert result.top_module == "counter"
    assert result.vivado_version == "2018.2"
    assert result.resources is not None
    assert result.resources["lut"] is not None
    assert "launch_runs impl_1" in fake.scripts[0]


def test_run_implementation_blocked_without_synthesis(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = ImplementationManager(FakeVivado(mode="blocked")).run_implementation(
        str(tmp_path)
    )
    assert result.success is False
    assert result.status == STATUS_BLOCKED
    assert result.reason == "Synthesis must complete before implementation"


def test_run_implementation_placement_failure(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = ImplementationManager(FakeVivado(mode="place_fail")).run_implementation(
        str(tmp_path)
    )
    assert result.success is False
    assert result.status == STATUS_FAILED
    assert result.failure_kind == "placement_failure"


def test_run_implementation_routing_failure(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = ImplementationManager(FakeVivado(mode="route_fail")).run_implementation(
        str(tmp_path)
    )
    assert result.success is False
    assert result.status == STATUS_FAILED
    assert result.failure_kind == "routing_failure"


def test_run_implementation_timeout(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = ImplementationManager(FakeVivado(mode="timeout")).run_implementation(
        str(tmp_path)
    )
    assert result.success is False
    assert result.status == STATUS_TIMEOUT
    assert "timeout" in (result.message or "").lower()


def test_get_implementation_status_not_started(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = ImplementationManager(FakeVivado()).get_implementation_status(
        str(tmp_path)
    )
    assert result.success is True
    assert result.status == STATUS_NOT_STARTED


def test_get_implemented_utilization_after_impl(tmp_path: Path) -> None:
    _make_project(tmp_path)
    report_dir = tmp_path / ".vivado_mcp" / "reports"
    fake = FakeVivado(mode="success", report_dir_hint=report_dir)
    assert ImplementationManager(fake).run_implementation(str(tmp_path)).success
    util = ImplementationManager(fake).get_implemented_utilization(str(tmp_path))
    assert util.success is True
    assert util.status == STATUS_AVAILABLE
    assert util.stage == "implementation"
    assert util.resources is not None
    assert util.resources["lut"]["used"] == 12
    assert util.resources["ff"] is not None
    assert "bram" in util.resources


def test_get_implemented_utilization_before_impl(tmp_path: Path) -> None:
    _make_project(tmp_path)
    result = ImplementationManager(FakeVivado()).get_implemented_utilization(
        str(tmp_path)
    )
    assert result.success is True
    assert result.status == STATUS_NOT_AVAILABLE
    assert result.reason is not None


def test_get_timing_prefers_implementation(tmp_path: Path) -> None:
    _make_project(tmp_path)
    report_dir = tmp_path / ".vivado_mcp" / "reports"
    fake = FakeVivado(mode="success", report_dir_hint=report_dir)
    assert ImplementationManager(fake).run_implementation(str(tmp_path)).success
    timing = ImplementationManager(fake).get_timing(str(tmp_path))
    assert timing.success is True
    assert timing.status == STATUS_AVAILABLE
    assert timing.stage == "implementation"
    assert timing.timing is not None
    assert timing.timing["wns_ns"] == 1.24
    assert timing.timing["status"] == "met"


def test_get_timing_failed_values(tmp_path: Path) -> None:
    _make_project(tmp_path)
    report_dir = tmp_path / ".vivado_mcp" / "reports"
    fake = FakeVivado(mode="timing_fail", report_dir_hint=report_dir)
    assert ImplementationManager(fake).run_implementation(str(tmp_path)).success
    timing = ImplementationManager(fake).get_timing(str(tmp_path))
    assert timing.status == STATUS_AVAILABLE
    assert timing.stage == "implementation"
    assert timing.timing is not None
    assert timing.timing["wns_ns"] == -0.42
    assert timing.timing["failing_endpoints"] == 4
    assert timing.timing["status"] == "failed"


def test_get_timing_no_constraints(tmp_path: Path) -> None:
    _make_project(tmp_path)
    report_dir = tmp_path / ".vivado_mcp" / "reports"
    fake = FakeVivado(mode="no_timing", report_dir_hint=report_dir)
    assert ImplementationManager(fake).run_implementation(str(tmp_path)).success
    timing = ImplementationManager(fake).get_timing(str(tmp_path))
    assert timing.success is True
    assert timing.status == STATUS_NOT_AVAILABLE
    assert timing.stage == "implementation"
    assert "constraint" in (timing.reason or timing.message or "").lower()


def test_get_timing_before_impl_falls_back(tmp_path: Path) -> None:
    _make_project(tmp_path)
    timing = ImplementationManager(FakeVivado()).get_timing(str(tmp_path))
    assert timing.success is True
    assert timing.status == STATUS_NOT_AVAILABLE or timing.stage == "synthesis"


def test_invalid_project_path() -> None:
    result = ImplementationManager(FakeVivado()).run_implementation(
        "/no/such/project.xpr"
    )
    assert result.success is False
    assert result.error is not None


def test_path_traversal_rejected(tmp_path: Path) -> None:
    result = ImplementationManager(FakeVivado()).run_implementation(
        str(tmp_path / ".." / ".." / "etc" / "passwd")
    )
    assert result.success is False


def test_classify_impl_run_status() -> None:
    assert classify_impl_run_status("route_design Complete!") == "completed"
    assert classify_impl_run_status("place_design ERROR") == "failed"
    assert classify_impl_run_status("Not started") == "not_started"
    assert classify_impl_run_status("") == "unknown"
    assert (
        VivadoReportParser().parse_implementation_status("route_design Complete!")
        == "completed"
    )


def test_classify_impl_failure_kinds() -> None:
    assert (
        classify_impl_failure("place_design ERROR", "Failed to place")
        == "placement_failure"
    )
    assert (
        classify_impl_failure("route_design ERROR", "unroutable nets")
        == "routing_failure"
    )
    assert (
        classify_impl_failure("ERROR", "invalid constraint in xdc")
        == "constraint_failure"
    )


def test_malformed_and_missing_reports_do_not_crash(tmp_path: Path) -> None:
    _make_project(tmp_path)
    report_dir = tmp_path / ".vivado_mcp" / "reports"
    report_dir.mkdir(parents=True)
    (report_dir / "impl_utilization.rpt").write_text("not a report\n", encoding="utf-8")
    (report_dir / "impl_timing_summary.rpt").write_text("", encoding="utf-8")
    status = tmp_path / ".vivado_mcp" / "last_implementation.json"
    status.write_text(
        '{"success": true, "status": "completed"}\n', encoding="utf-8"
    )
    fake = FakeVivado(report_dir_hint=report_dir)
    util = ImplementationManager(fake).get_implemented_utilization(str(tmp_path))
    assert util.success is True
    assert util.status in {STATUS_AVAILABLE, STATUS_NOT_AVAILABLE}
    timing = ImplementationManager(fake).get_timing(str(tmp_path))
    assert timing.success is True
