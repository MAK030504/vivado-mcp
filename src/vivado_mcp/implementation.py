"""Implementation (place & route) and post-implementation reporting.

Runs implementation through controlled Vivado batch Tcl, writes utilization
and timing reports under ``.vivado_mcp/reports/``, and returns structured MCP
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
    ImplementationError,
    ImplementationNotRunError,
    ReportNotAvailableError,
    VivadoExecutionError,
    VivadoMCPError,
    VivadoNotFoundError,
)
from vivado_mcp.projects import resolve_xpr_path
from vivado_mcp.reports import (
    ResourceUsage,
    VivadoReportParser,
    classify_impl_failure,
    classify_impl_run_status,
    parse_timing_file,
    parse_utilization_file,
)
from vivado_mcp.tcl import (
    build_impl_status_tcl,
    build_report_impl_timing_tcl,
    build_report_impl_utilization_tcl,
    build_run_implementation_tcl,
)
from vivado_mcp.vivado import Vivado

logger = logging.getLogger(__name__)

_MARKER_PATTERN = re.compile(r"^VIVADO_MCP_([A-Z0-9_]+)=(.*)$", re.MULTILINE)
_ARTIFACT_DIR = ".vivado_mcp"
_REPORT_DIR = "reports"
_STATUS_FILE = "last_implementation.json"
_UTIL_REPORT = "impl_utilization.rpt"
_TIMING_REPORT = "impl_timing_summary.rpt"

STATUS_NOT_STARTED = "not_started"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_UNKNOWN = "unknown"
STATUS_BLOCKED = "blocked"
STATUS_TIMEOUT = "timeout"
STATUS_AVAILABLE = "available"
STATUS_NOT_AVAILABLE = "not_available"

# Implementation can take significantly longer than synthesis.
_IMPL_TIMEOUT_S = 7200.0
_REPORT_TIMEOUT_S = 600.0


@dataclass(frozen=True, slots=True)
class ImplementationResult:
    """Structured result for implementation / report operations."""

    success: bool
    status: str | None = None
    message: str | None = None
    project_path: str | None = None
    run: str | None = "impl_1"
    top_module: str | None = None
    vivado_version: str | None = None
    log_summary: str | None = None
    errors: list[str] | None = None
    warnings: list[str] | None = None
    resources: dict[str, dict[str, int | float] | None] | None = None
    timing: dict[str, Any] | None = None
    report_path: str | None = None
    reason: str | None = None
    failure_kind: str | None = None
    stage: str | None = None
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
        if self.run is not None:
            payload["run"] = self.run
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
        if self.failure_kind is not None:
            payload["failure_kind"] = self.failure_kind
        if self.stage is not None:
            payload["stage"] = self.stage
        if self.error is not None:
            payload["error"] = self.error
        for key, value in self.extra.items():
            if key not in payload:
                payload[key] = value
        return payload


class ImplementationManager:
    """Run implementation and collect post-route utilization / timing."""

    def __init__(self, vivado: Vivado | None = None) -> None:
        self.vivado = vivado or Vivado()
        self._parser = VivadoReportParser()

    def run_implementation(self, project_path: str) -> ImplementationResult:
        """Run Vivado place & route for ``project_path`` in batch mode."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            report_dir = _report_dir(project_dir)
            version = self._vivado_version_or_raise()

            script = build_run_implementation_tcl(
                xpr_path=xpr_path,
                report_dir=report_dir,
            )
            stdout = ""
            stderr = ""
            try:
                result = self.vivado.run_tcl(script, timeout=_IMPL_TIMEOUT_S)
                stdout = result.stdout
                stderr = result.stderr
            except VivadoExecutionError as exc:
                stdout = exc.stdout
                stderr = exc.stderr
                if _is_timeout_error(exc):
                    timed = ImplementationResult(
                        success=False,
                        status=STATUS_TIMEOUT,
                        message=(
                            "Vivado implementation exceeded the configured timeout"
                        ),
                        project_path=str(project_dir),
                        vivado_version=version,
                        log_summary=_trim_output(stdout, stderr, limit=2500),
                        failure_kind="implementation_tool_failure",
                        error={
                            "type": "ImplementationError",
                            "code": "implementation_timeout",
                            "message": (
                                "Vivado implementation exceeded the configured timeout"
                            ),
                            "status": STATUS_TIMEOUT,
                        },
                    )
                    _write_status(project_dir, timed)
                    return timed
                return self._implementation_failure(
                    project_dir=project_dir,
                    version=version,
                    stdout=stdout,
                    stderr=stderr,
                )

            markers = _parse_markers(stdout)
            err_list, warn_list = self._parser.extract_errors_warnings(
                "\n".join(part for part in (stdout, stderr) if part)
            )
            top = markers.get("IMPL_TOP")
            run_status = markers.get("IMPL_RUN_STATUS", "")
            impl_status = (markers.get("IMPL_STATUS") or "").lower()

            if impl_status == STATUS_BLOCKED or (
                markers.get("STATUS") != "OK"
                and "synthesis must complete" in (markers.get("IMPL_ERROR") or "").lower()
            ):
                reason = (
                    markers.get("IMPL_ERROR")
                    or "Synthesis must complete before implementation"
                )
                if "synthesis must complete" in reason.lower():
                    reason = "Synthesis must complete before implementation"
                blocked = ImplementationResult(
                    success=False,
                    status=STATUS_BLOCKED,
                    reason=reason,
                    message=reason,
                    project_path=str(project_dir),
                    top_module=top,
                    vivado_version=version,
                    log_summary=_trim_output(stdout, stderr, limit=2500),
                    errors=err_list,
                    warnings=warn_list,
                    extra={"impl_run_status": run_status or None},
                )
                _write_status(project_dir, blocked)
                return blocked

            if markers.get("STATUS") != "OK" or impl_status == STATUS_FAILED:
                return self._implementation_failure(
                    project_dir=project_dir,
                    version=version,
                    stdout=stdout,
                    stderr=stderr,
                    top_module=top,
                    run_status=run_status,
                    marker_error=markers.get("IMPL_ERROR"),
                    errors=err_list,
                    warnings=warn_list,
                )

            util_path = report_dir / _UTIL_REPORT
            timing_path = report_dir / _TIMING_REPORT
            resources = None
            timing = None
            if util_path.is_file():
                resources = _resources_to_dict(parse_utilization_file(util_path))
            if timing_path.is_file():
                summary = parse_timing_file(timing_path)
                if summary is not None:
                    timing = summary.to_dict()

            result = ImplementationResult(
                success=True,
                status=STATUS_COMPLETED,
                message="Implementation completed successfully",
                project_path=str(project_dir),
                run="impl_1",
                top_module=top,
                vivado_version=version,
                log_summary=_trim_output(stdout, stderr, limit=2500),
                errors=err_list,
                warnings=warn_list,
                resources=resources,
                timing=timing,
                report_path=str(util_path) if util_path.is_file() else None,
                extra={
                    "impl_run_status": run_status or None,
                    "timing_report_path": (
                        str(timing_path) if timing_path.is_file() else None
                    ),
                    "utilization_report_path": (
                        str(util_path) if util_path.is_file() else None
                    ),
                    "timing_status": markers.get("TIMING_STATUS"),
                },
            )
            _write_status(project_dir, result)
            return result
        except VivadoMCPError as exc:
            return _failure(exc)

    def get_implementation_status(self, project_path: str) -> ImplementationResult:
        """Return structured status for ``impl_1`` without launching a run."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            version = self._vivado_version_or_raise()

            script = build_impl_status_tcl(xpr_path=xpr_path)
            try:
                result = self.vivado.run_tcl(script, timeout=_REPORT_TIMEOUT_S)
                stdout = result.stdout
                stderr = result.stderr
            except VivadoExecutionError as exc:
                return ImplementationResult(
                    success=False,
                    status=STATUS_UNKNOWN,
                    message=exc.message,
                    project_path=str(project_dir),
                    vivado_version=version,
                    log_summary=_trim_output(exc.stdout, exc.stderr, limit=1500),
                    error={
                        "type": "ImplementationError",
                        "code": "implementation_error",
                        "message": exc.message,
                        "status": STATUS_UNKNOWN,
                    },
                )

            markers = _parse_markers(stdout)
            raw = markers.get("IMPL_RUN_STATUS") or markers.get("IMPL_STATUS") or ""
            status = self._parser.parse_implementation_status(raw)
            if markers.get("IMPL_STATUS", "").lower() == STATUS_NOT_STARTED:
                status = STATUS_NOT_STARTED

            last = _load_status(project_dir)
            if status == STATUS_UNKNOWN and last and last.get("status") in {
                STATUS_COMPLETED,
                STATUS_FAILED,
                STATUS_CANCELLED,
                STATUS_BLOCKED,
                STATUS_TIMEOUT,
                STATUS_NOT_STARTED,
            }:
                status = str(last["status"])

            return ImplementationResult(
                success=True,
                status=status,
                message=f"Implementation status: {status}",
                project_path=str(project_dir),
                run="impl_1",
                vivado_version=version,
                extra={
                    "vivado_status": raw or None,
                    "progress": markers.get("IMPL_PROGRESS"),
                    "synth_run_status": markers.get("SYNTH_RUN_STATUS"),
                },
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def get_implemented_utilization(self, project_path: str) -> ImplementationResult:
        """Return structured post-implementation utilization."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            report_path = _report_dir(project_dir) / _UTIL_REPORT

            if not self._implementation_completed(project_dir):
                return ImplementationResult(
                    success=True,
                    status=STATUS_NOT_AVAILABLE,
                    stage="implementation",
                    reason=(
                        "Implementation has not completed for this project. "
                        "Call run_implementation first."
                    ),
                    project_path=str(project_dir),
                    vivado_version=self._vivado_version_or_none(),
                )

            if not report_path.is_file():
                self._regenerate_utilization(xpr_path, report_path)

            if not report_path.is_file():
                return ImplementationResult(
                    success=True,
                    status=STATUS_NOT_AVAILABLE,
                    stage="implementation",
                    reason="Implemented utilization report was not generated.",
                    project_path=str(project_dir),
                    vivado_version=self._vivado_version_or_none(),
                )

            resources = _resources_to_dict(parse_utilization_file(report_path))
            return ImplementationResult(
                success=True,
                status=STATUS_AVAILABLE,
                stage="implementation",
                message="Post-implementation utilization report available",
                project_path=str(project_dir),
                resources=resources,
                report_path=str(report_path),
                vivado_version=self._vivado_version_or_none(),
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def get_timing(self, project_path: str) -> ImplementationResult:
        """Return timing, preferring post-implementation when available.

        Falls back to post-synthesis timing (Milestone 5) when implementation
        has not completed or post-route timing is unavailable.
        """
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            report_path = _report_dir(project_dir) / _TIMING_REPORT

            if self._implementation_completed(project_dir) or report_path.is_file():
                if not report_path.is_file():
                    try:
                        self._regenerate_timing(xpr_path, report_path)
                    except VivadoMCPError as exc:
                        # Fall through to synthesis timing below.
                        logger.info(
                            "Post-implementation timing unavailable: %s", exc.message
                        )

                if report_path.is_file():
                    summary = parse_timing_file(report_path)
                    if summary is None:
                        return ImplementationResult(
                            success=True,
                            status=STATUS_NOT_AVAILABLE,
                            stage="implementation",
                            reason="No timing constraints available",
                            message="No timing constraints available",
                            project_path=str(project_dir),
                            report_path=str(report_path),
                            vivado_version=self._vivado_version_or_none(),
                        )
                    return ImplementationResult(
                        success=True,
                        status=STATUS_AVAILABLE,
                        stage="implementation",
                        message="Post-implementation timing summary available",
                        project_path=str(project_dir),
                        timing=summary.to_dict(),
                        report_path=str(report_path),
                        vivado_version=self._vivado_version_or_none(),
                    )

            # Preserve Milestone 5 post-synthesis timing behavior.
            from vivado_mcp.synthesis import SynthesisManager

            synth = SynthesisManager(self.vivado)
            synth_result = synth.get_timing(project_path)
            payload = synth_result.to_dict()
            return ImplementationResult(
                success=bool(payload.get("success")),
                status=str(payload.get("status")) if payload.get("status") else None,
                stage="synthesis",
                message=str(payload["message"]) if payload.get("message") else None,
                project_path=str(project_dir),
                timing=payload.get("timing") if isinstance(payload.get("timing"), dict) else None,
                report_path=(
                    str(payload["report_path"])
                    if payload.get("report_path")
                    else None
                ),
                reason=str(payload["reason"]) if payload.get("reason") else None,
                vivado_version=self._vivado_version_or_none(),
                error=payload.get("error") if isinstance(payload.get("error"), dict) else None,
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def _implementation_failure(
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
    ) -> ImplementationResult:
        markers = _parse_markers(stdout)
        if errors is None or warnings is None:
            err_list, warn_list = self._parser.extract_errors_warnings(
                "\n".join(part for part in (stdout, stderr) if part)
            )
            errors = errors if errors is not None else err_list
            warnings = warnings if warnings is not None else warn_list

        combined = "\n".join(part for part in (stdout, stderr) if part)
        coarse = classify_impl_run_status(
            run_status or markers.get("IMPL_RUN_STATUS", "")
        )
        status = STATUS_FAILED
        if coarse in {
            STATUS_FAILED,
            STATUS_CANCELLED,
            STATUS_NOT_STARTED,
            STATUS_UNKNOWN,
        }:
            status = coarse if coarse != STATUS_NOT_STARTED else STATUS_FAILED
        if (markers.get("IMPL_STATUS") or "").lower() == STATUS_BLOCKED:
            status = STATUS_BLOCKED

        failure_kind = None
        if status == STATUS_FAILED:
            failure_kind = classify_impl_failure(
                run_status or markers.get("IMPL_RUN_STATUS", ""),
                combined,
            )

        message = (
            marker_error
            or markers.get("IMPL_ERROR")
            or "Implementation failed"
        )
        if errors and not marker_error:
            message = errors[0]

        result = ImplementationResult(
            success=False,
            status=status,
            message=message,
            reason=message if status == STATUS_BLOCKED else None,
            project_path=str(project_dir),
            top_module=top_module or markers.get("IMPL_TOP"),
            vivado_version=version,
            log_summary=_trim_output(stdout, stderr, limit=2500),
            errors=errors or [],
            warnings=warnings or [],
            failure_kind=failure_kind,
            error={
                "type": "ImplementationError",
                "code": "implementation_error",
                "message": message,
                "status": status,
            },
            extra={
                "impl_run_status": run_status or markers.get("IMPL_RUN_STATUS"),
                "failure_kind": failure_kind,
            },
        )
        _write_status(project_dir, result)
        return result

    def _implementation_completed(self, project_dir: Path) -> bool:
        status_path = _status_path(project_dir)
        if status_path.is_file():
            try:
                raw = json.loads(status_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("status") == STATUS_COMPLETED:
                    return True
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        if (_report_dir(project_dir) / _UTIL_REPORT).is_file():
            return True
        return False

    def _regenerate_utilization(self, xpr_path: Path, report_path: Path) -> None:
        self._vivado_version_or_raise()
        script = build_report_impl_utilization_tcl(
            xpr_path=xpr_path,
            report_path=report_path,
        )
        try:
            self.vivado.run_tcl(script, timeout=_REPORT_TIMEOUT_S)
        except VivadoExecutionError as exc:
            markers = _parse_markers(exc.stdout)
            if markers.get("IMPL_STATUS") == STATUS_NOT_STARTED:
                raise ImplementationNotRunError(
                    markers.get("IMPL_ERROR")
                    or "Implementation has not completed for this project."
                ) from exc
            raise ImplementationError(
                markers.get("IMPL_ERROR")
                or "Failed to regenerate implemented utilization report.",
                status=STATUS_FAILED,
                stdout=exc.stdout,
                stderr=exc.stderr,
            ) from exc

    def _regenerate_timing(self, xpr_path: Path, report_path: Path) -> None:
        self._vivado_version_or_raise()
        script = build_report_impl_timing_tcl(
            xpr_path=xpr_path,
            report_path=report_path,
        )
        try:
            self.vivado.run_tcl(script, timeout=_REPORT_TIMEOUT_S)
        except VivadoExecutionError as exc:
            markers = _parse_markers(exc.stdout)
            if markers.get("IMPL_STATUS") == STATUS_NOT_STARTED:
                raise ImplementationNotRunError(
                    markers.get("IMPL_ERROR")
                    or "Implementation has not completed for this project."
                ) from exc
            raise ReportNotAvailableError(
                markers.get("TIMING_ERROR")
                or markers.get("IMPL_ERROR")
                or "Timing report is not available after implementation.",
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


def _write_status(project_dir: Path, result: ImplementationResult) -> None:
    path = _status_path(project_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write implementation status artifact: %s", exc)


def _load_status(project_dir: Path) -> dict[str, Any] | None:
    path = _status_path(project_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


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


def _is_timeout_error(exc: VivadoExecutionError) -> bool:
    return "timed out" in (exc.message or "").lower()


def _failure(exc: VivadoMCPError) -> ImplementationResult:
    logger.info("Implementation operation failed: %s (%s)", exc.code, exc.message)
    status = STATUS_FAILED
    if isinstance(exc, ImplementationError):
        status = exc.status
    elif isinstance(exc, ImplementationNotRunError):
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
    elif isinstance(exc, ImplementationError):
        log_summary = _trim_output(exc.stdout, exc.stderr) or None
        if log_summary:
            error["vivado_output"] = log_summary

    return ImplementationResult(
        success=False,
        status=status,
        message=exc.message,
        log_summary=log_summary,
        error=error,
        reason=(
            exc.message
            if isinstance(exc, (ImplementationNotRunError, ReportNotAvailableError))
            else None
        ),
    )
