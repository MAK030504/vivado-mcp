"""Synthesis and post-synthesis reporting for Vivado projects.

Runs synthesis through controlled Vivado batch Tcl, writes utilization and
timing reports under ``.vivado_mcp/reports/``, and returns structured MCP
results. Never exposes arbitrary shell or Tcl execution.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vivado_mcp.errors import (
    ReportNotAvailableError,
    SynthesisError,
    SynthesisNotRunError,
    VivadoExecutionError,
    VivadoMCPError,
    VivadoNotFoundError,
)
from vivado_mcp.projects import resolve_xpr_path
from vivado_mcp.reports import (
    ResourceUsage,
    TimingSummary,
    VivadoReportParser,
    classify_synth_run_status,
    parse_timing_file,
    parse_utilization_file,
)
from vivado_mcp.tcl import (
    build_report_timing_tcl,
    build_report_utilization_tcl,
    build_run_synthesis_tcl,
)
from vivado_mcp.vivado import Vivado

logger = logging.getLogger(__name__)

_MARKER_PATTERN = re.compile(r"^VIVADO_MCP_([A-Z0-9_]+)=(.*)$", re.MULTILINE)
_ARTIFACT_DIR = ".vivado_mcp"
_REPORT_DIR = "reports"
_STATUS_FILE = "last_synthesis.json"
_UTIL_REPORT = "utilization.rpt"
_TIMING_REPORT = "timing_summary.rpt"

STATUS_NOT_STARTED = "not_started"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_UNKNOWN = "unknown"
STATUS_AVAILABLE = "available"
STATUS_NOT_AVAILABLE = "not_available"


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """Structured result for synthesis / report operations."""

    success: bool
    status: str | None = None
    message: str | None = None
    project_path: str | None = None
    top_module: str | None = None
    vivado_version: str | None = None
    log_summary: str | None = None
    errors: list[str] | None = None
    warnings: list[str] | None = None
    resources: dict[str, dict[str, int | float] | None] | None = None
    timing: dict[str, Any] | None = None
    report_path: str | None = None
    reason: str | None = None
    error: dict[str, str] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"success": self.success}
        if self.status is not None:
            payload["status"] = self.status
        if self.message is not None:
            payload["message"] = self.message
        if self.project_path is not None:
            payload["project"] = self.project_path
            payload["project_path"] = self.project_path
        if self.top_module is not None:
            payload["top_module"] = self.top_module
        if self.vivado_version is not None:
            payload["vivado_version"] = self.vivado_version
        if self.log_summary is not None:
            payload["log_summary"] = self.log_summary
        if self.errors is not None:
            payload["errors"] = self.errors
        if self.warnings is not None:
            payload["warnings"] = self.warnings
        if self.resources is not None:
            payload["resources"] = self.resources
        if self.timing is not None:
            payload["timing"] = self.timing
        if self.report_path is not None:
            payload["report_path"] = self.report_path
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.error is not None:
            payload["error"] = self.error
        for key, value in self.extra.items():
            if key not in payload:
                payload[key] = value
        return payload


class SynthesisManager:
    """Run synthesis and collect utilization / timing reports."""

    def __init__(self, vivado: Vivado | None = None) -> None:
        self.vivado = vivado or Vivado()
        self._parser = VivadoReportParser()

    def run_synthesis(self, project_path: str) -> SynthesisResult:
        """Run Vivado synthesis for ``project_path`` in batch mode."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            report_dir = _report_dir(project_dir)
            version = self._vivado_version_or_raise()

            script = build_run_synthesis_tcl(
                xpr_path=xpr_path,
                report_dir=report_dir,
            )
            stdout = ""
            stderr = ""
            try:
                # Synthesis can take a long time on real designs.
                result = self.vivado.run_tcl(script, timeout=3600.0)
                stdout = result.stdout
                stderr = result.stderr
            except VivadoExecutionError as exc:
                stdout = exc.stdout
                stderr = exc.stderr
                return self._synthesis_failure(
                    project_dir=project_dir,
                    version=version,
                    stdout=stdout,
                    stderr=stderr,
                )

            markers = _parse_markers(stdout)
            err_list, warn_list = self._parser.extract_errors_warnings(
                "\n".join(part for part in (stdout, stderr) if part)
            )
            top = markers.get("SYNTH_TOP")
            run_status = markers.get("SYNTH_RUN_STATUS", "")
            synth_status = markers.get("SYNTH_STATUS", "").lower()

            if markers.get("STATUS") != "OK" or synth_status == STATUS_FAILED:
                failure = self._synthesis_failure(
                    project_dir=project_dir,
                    version=version,
                    stdout=stdout,
                    stderr=stderr,
                    top_module=top,
                    run_status=run_status,
                    marker_error=markers.get("SYNTH_ERROR"),
                    errors=err_list,
                    warnings=warn_list,
                )
                return failure

            util_path = report_dir / _UTIL_REPORT
            timing_path = report_dir / _TIMING_REPORT
            result = SynthesisResult(
                success=True,
                status=STATUS_COMPLETED,
                message="Synthesis completed successfully",
                project_path=str(project_dir),
                top_module=top,
                vivado_version=version,
                log_summary=_trim_output(stdout, stderr, limit=2500),
                errors=err_list,
                warnings=warn_list,
                report_path=str(util_path) if util_path.is_file() else None,
                extra={
                    "synth_run_status": run_status or None,
                    "timing_report_path": (
                        str(timing_path) if timing_path.is_file() else None
                    ),
                    "utilization_report_path": (
                        str(util_path) if util_path.is_file() else None
                    ),
                },
            )
            _write_status(project_dir, result)
            return result
        except VivadoMCPError as exc:
            return _failure(exc)

    def get_utilization(self, project_path: str) -> SynthesisResult:
        """Return structured post-synthesis utilization for ``project_path``."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            report_path = _report_dir(project_dir) / _UTIL_REPORT

            if not self._synthesis_completed(project_dir, xpr_path):
                return SynthesisResult(
                    success=True,
                    status=STATUS_NOT_AVAILABLE,
                    reason=(
                        "Synthesis has not completed for this project. "
                        "Call run_synthesis first."
                    ),
                    project_path=str(project_dir),
                    vivado_version=self._vivado_version_or_none(),
                )

            if not report_path.is_file():
                self._regenerate_utilization(xpr_path, report_path)

            if not report_path.is_file():
                return SynthesisResult(
                    success=True,
                    status=STATUS_NOT_AVAILABLE,
                    reason="Utilization report was not generated.",
                    project_path=str(project_dir),
                    vivado_version=self._vivado_version_or_none(),
                )

            resources = parse_utilization_file(report_path)
            return SynthesisResult(
                success=True,
                status=STATUS_AVAILABLE,
                message="Utilization report available",
                project_path=str(project_dir),
                resources=_resources_to_dict(resources),
                report_path=str(report_path),
                vivado_version=self._vivado_version_or_none(),
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def get_timing(self, project_path: str) -> SynthesisResult:
        """Return structured post-synthesis timing for ``project_path``.

        Post-synthesis timing is estimated and is not final implementation
        timing. When constraints are missing, returns ``not_available``.
        """
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            report_path = _report_dir(project_dir) / _TIMING_REPORT

            if not self._synthesis_completed(project_dir, xpr_path):
                return SynthesisResult(
                    success=True,
                    status=STATUS_NOT_AVAILABLE,
                    reason=(
                        "Synthesis has not completed for this project. "
                        "Call run_synthesis first."
                    ),
                    project_path=str(project_dir),
                    vivado_version=self._vivado_version_or_none(),
                )

            if not report_path.is_file():
                try:
                    self._regenerate_timing(xpr_path, report_path)
                except VivadoMCPError as exc:
                    return SynthesisResult(
                        success=True,
                        status=STATUS_NOT_AVAILABLE,
                        reason=exc.message
                        or (
                            "Post-synthesis timing analysis is not available. "
                            "Add timing constraints (XDC) and/or run "
                            "implementation for final timing."
                        ),
                        project_path=str(project_dir),
                        vivado_version=self._vivado_version_or_none(),
                    )

            if not report_path.is_file():
                return SynthesisResult(
                    success=True,
                    status=STATUS_NOT_AVAILABLE,
                    reason=(
                        "Timing report file was not produced. "
                        "Synthesis timing may be unavailable without constraints."
                    ),
                    project_path=str(project_dir),
                    vivado_version=self._vivado_version_or_none(),
                )

            summary = parse_timing_file(report_path)
            if summary is None:
                return SynthesisResult(
                    success=True,
                    status=STATUS_NOT_AVAILABLE,
                    reason=(
                        "No timing constraints / timing data found after synthesis. "
                        "Add XDC constraints and/or run implementation for "
                        "post-route timing via get_timing."
                    ),
                    project_path=str(project_dir),
                    report_path=str(report_path),
                    vivado_version=self._vivado_version_or_none(),
                )

            return SynthesisResult(
                success=True,
                status=STATUS_AVAILABLE,
                message=(
                    "Post-synthesis timing summary available "
                    "(estimated; not final implementation timing)."
                ),
                project_path=str(project_dir),
                timing=summary.to_dict(),
                report_path=str(report_path),
                vivado_version=self._vivado_version_or_none(),
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def _synthesis_failure(
        self,
        *,
        project_dir: Path,
        version: str | None,
        stdout: str,
        stderr: str,
        top_module: str | None = None,
        run_status: str = "",
        marker_error: str | None = None,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> SynthesisResult:
        markers = _parse_markers(stdout)
        if errors is None or warnings is None:
            err_list, warn_list = self._parser.extract_errors_warnings(
                "\n".join(part for part in (stdout, stderr) if part)
            )
            errors = errors if errors is not None else err_list
            warnings = warnings if warnings is not None else warn_list

        status = STATUS_FAILED
        coarse = classify_synth_run_status(
            run_status or markers.get("SYNTH_RUN_STATUS", "")
        )
        if coarse in {
            STATUS_FAILED,
            STATUS_CANCELLED,
            STATUS_NOT_STARTED,
            STATUS_UNKNOWN,
        }:
            status = coarse if coarse != STATUS_NOT_STARTED else STATUS_FAILED

        message = (
            marker_error
            or markers.get("SYNTH_ERROR")
            or "Synthesis failed"
        )
        if errors and not marker_error:
            message = errors[0]

        result = SynthesisResult(
            success=False,
            status=status,
            message=message,
            project_path=str(project_dir),
            top_module=top_module or markers.get("SYNTH_TOP"),
            vivado_version=version,
            log_summary=_trim_output(stdout, stderr, limit=2500),
            errors=errors or [],
            warnings=warnings or [],
            error={
                "type": "SynthesisError",
                "code": "synthesis_error",
                "message": message,
                "status": status,
            },
            extra={"synth_run_status": run_status or markers.get("SYNTH_RUN_STATUS")},
        )
        _write_status(project_dir, result)
        return result

    def _synthesis_completed(self, project_dir: Path, xpr_path: Path) -> bool:
        status_path = _status_path(project_dir)
        if status_path.is_file():
            try:
                raw = json.loads(status_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("status") == STATUS_COMPLETED:
                    return True
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        # Fall back: utilization report presence after a prior successful synth.
        if (_report_dir(project_dir) / _UTIL_REPORT).is_file():
            return True
        return False

    def _regenerate_utilization(self, xpr_path: Path, report_path: Path) -> None:
        version = self._vivado_version_or_raise()
        del version  # used only for validation
        script = build_report_utilization_tcl(
            xpr_path=xpr_path,
            report_path=report_path,
        )
        try:
            self.vivado.run_tcl(script, timeout=600.0)
        except VivadoExecutionError as exc:
            markers = _parse_markers(exc.stdout)
            if markers.get("SYNTH_STATUS") == STATUS_NOT_STARTED:
                raise SynthesisNotRunError(
                    markers.get("SYNTH_ERROR")
                    or "Synthesis has not completed for this project."
                ) from exc
            raise SynthesisError(
                markers.get("SYNTH_ERROR") or "Failed to regenerate utilization report.",
                status=STATUS_FAILED,
                stdout=exc.stdout,
                stderr=exc.stderr,
            ) from exc

    def _regenerate_timing(self, xpr_path: Path, report_path: Path) -> None:
        self._vivado_version_or_raise()
        script = build_report_timing_tcl(
            xpr_path=xpr_path,
            report_path=report_path,
        )
        try:
            self.vivado.run_tcl(script, timeout=600.0)
        except VivadoExecutionError as exc:
            markers = _parse_markers(exc.stdout)
            if markers.get("SYNTH_STATUS") == STATUS_NOT_STARTED:
                raise SynthesisNotRunError(
                    markers.get("SYNTH_ERROR")
                    or "Synthesis has not completed for this project."
                ) from exc
            raise ReportNotAvailableError(
                markers.get("TIMING_ERROR")
                or markers.get("SYNTH_ERROR")
                or "Timing report is not available after synthesis.",
                status=STATUS_NOT_AVAILABLE,
            ) from exc

    def _vivado_version_or_raise(self) -> str | None:
        info = self.vivado.get_version()
        if not info.installed:
            raise VivadoNotFoundError(
                info.message
                or "Vivado was not found. Set VIVADO_PATH to vivado.bat / vivado."
            )
        return info.version

    def _vivado_version_or_none(self) -> str | None:
        try:
            return self._vivado_version_or_raise()
        except VivadoMCPError:
            return None


def _resources_to_dict(
    resources: dict[str, ResourceUsage | None],
) -> dict[str, dict[str, int | float] | None]:
    return {
        key: (value.to_dict() if value is not None else None)
        for key, value in resources.items()
    }


def _report_dir(project_dir: Path) -> Path:
    return project_dir / _ARTIFACT_DIR / _REPORT_DIR


def _status_path(project_dir: Path) -> Path:
    return project_dir / _ARTIFACT_DIR / _STATUS_FILE


def _write_status(project_dir: Path, result: SynthesisResult) -> None:
    path = _status_path(project_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write synthesis status artifact: %s", exc)


def _parse_markers(stdout: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2).strip()
        for match in _MARKER_PATTERN.finditer(stdout)
    }


def _trim_output(stdout: str, stderr: str, *, limit: int = 4000) -> str:
    combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    if len(combined) <= limit:
        return combined
    return combined[: limit - 20] + "\n...[truncated]..."


def _failure(exc: VivadoMCPError) -> SynthesisResult:
    logger.info("Synthesis operation failed: %s (%s)", exc.code, exc.message)
    status = STATUS_FAILED
    if isinstance(exc, SynthesisError):
        status = exc.status
    elif isinstance(exc, SynthesisNotRunError):
        status = STATUS_NOT_STARTED
    elif isinstance(exc, ReportNotAvailableError):
        status = exc.status

    error: dict[str, str] = {
        "type": type(exc).__name__,
        "code": exc.code,
        "message": exc.message,
    }
    log_summary = None
    if isinstance(exc, VivadoExecutionError):
        log_summary = _trim_output(exc.stdout, exc.stderr)
        if log_summary:
            error["vivado_output"] = log_summary
    elif isinstance(exc, SynthesisError):
        log_summary = _trim_output(exc.stdout, exc.stderr) or None
        if log_summary:
            error["vivado_output"] = log_summary

    return SynthesisResult(
        success=False,
        status=status,
        message=exc.message,
        log_summary=log_summary,
        error=error,
        reason=exc.message if isinstance(exc, (SynthesisNotRunError, ReportNotAvailableError)) else None,
    )
