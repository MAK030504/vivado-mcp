"""Bitstream generation and validation for Vivado projects.

Runs write_bitstream through controlled Vivado batch Tcl via the shared
``Vivado`` runner, validates the generated ``.bit`` file under the project
tree, and returns structured MCP results. Does not program FPGA boards.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vivado_mcp.errors import (
    BitstreamError,
    VivadoExecutionError,
    VivadoMCPError,
    VivadoNotFoundError,
)
from vivado_mcp.projects import resolve_xpr_path
from vivado_mcp.reports import VivadoReportParser, classify_bitstream_run_status
from vivado_mcp.tcl import build_bitstream_status_tcl, build_generate_bitstream_tcl
from vivado_mcp.vivado import Vivado

logger = logging.getLogger(__name__)

_MARKER_PATTERN = re.compile(r"^VIVADO_MCP_([A-Z0-9_]+)=(.*)$", re.MULTILINE)
_ARTIFACT_DIR = ".vivado_mcp"
_STATUS_FILE = "last_bitstream.json"

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

# Bitstream generation (write_bitstream step) can still take a long time on
# larger devices; reuse a long configurable timeout via Vivado.run_tcl.
_BITSTREAM_TIMEOUT_S = 7200.0
_STATUS_TIMEOUT_S = 600.0

_BLOCKED_GENERATE_REASON = "Implementation must complete before bitstream generation"
_BLOCKED_STATUS_REASON = "Implementation has not completed"


@dataclass(frozen=True, slots=True)
class BitstreamResult:
    """Structured result for bitstream generation / query operations."""

    success: bool
    status: str | None = None
    message: str | None = None
    project_path: str | None = None
    top_module: str | None = None
    vivado_version: str | None = None
    log_summary: str | None = None
    errors: list[str] | None = None
    warnings: list[str] | None = None
    bitstream: dict[str, Any] | None = None
    bitstream_exists: bool | None = None
    path: str | None = None
    filename: str | None = None
    size_bytes: int | None = None
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
        if self.bitstream is not None:
            payload["bitstream"] = self.bitstream
        if self.bitstream_exists is not None:
            payload["bitstream_exists"] = self.bitstream_exists
        if self.path is not None or self.status == STATUS_NOT_AVAILABLE:
            payload["path"] = self.path
        if self.filename is not None:
            payload["filename"] = self.filename
        if self.size_bytes is not None:
            payload["size_bytes"] = self.size_bytes
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.error is not None:
            payload["error"] = self.error
        for key, value in self.extra.items():
            if key not in payload:
                payload[key] = value
        return payload


class BitstreamManager:
    """Generate and locate FPGA bitstreams using the shared Vivado runner."""

    def __init__(self, vivado: Vivado | None = None) -> None:
        self.vivado = vivado or Vivado()
        self._parser = VivadoReportParser()

    def generate_bitstream(self, project_path: str) -> BitstreamResult:
        """Generate a ``.bit`` file for ``project_path`` in Vivado batch mode."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            version = self._vivado_version_or_raise()

            script = build_generate_bitstream_tcl(xpr_path=xpr_path)
            stdout = ""
            stderr = ""
            try:
                result = self.vivado.run_tcl(script, timeout=_BITSTREAM_TIMEOUT_S)
                stdout = result.stdout
                stderr = result.stderr
            except VivadoExecutionError as exc:
                stdout = exc.stdout
                stderr = exc.stderr
                if _is_timeout_error(exc):
                    timed = BitstreamResult(
                        success=False,
                        status=STATUS_TIMEOUT,
                        message=(
                            "Bitstream generation exceeded the configured timeout"
                        ),
                        project_path=str(project_dir),
                        vivado_version=version,
                        log_summary=_trim_output(stdout, stderr, limit=2500),
                        errors=[],
                        warnings=[],
                        error={
                            "type": "BitstreamError",
                            "code": "bitstream_timeout",
                            "message": (
                                "Bitstream generation exceeded the configured timeout"
                            ),
                            "status": STATUS_TIMEOUT,
                        },
                    )
                    _write_status(project_dir, timed)
                    return timed
                return self._bitstream_failure(
                    project_dir=project_dir,
                    version=version,
                    stdout=stdout,
                    stderr=stderr,
                )

            markers = _parse_markers(stdout)
            err_list, warn_list = self._parser.extract_errors_warnings(
                "\n".join(part for part in (stdout, stderr) if part)
            )
            top = markers.get("BITSTREAM_TOP")
            bit_status = (markers.get("BITSTREAM_STATUS") or "").lower()
            run_status = markers.get("IMPL_RUN_STATUS", "")

            if bit_status == STATUS_BLOCKED or (
                markers.get("STATUS") != "OK"
                and _BLOCKED_GENERATE_REASON.lower()
                in (markers.get("BITSTREAM_ERROR") or "").lower()
            ):
                reason = markers.get("BITSTREAM_ERROR") or _BLOCKED_GENERATE_REASON
                if "implementation must complete" in reason.lower():
                    reason = _BLOCKED_GENERATE_REASON
                blocked = BitstreamResult(
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

            if markers.get("STATUS") != "OK" or bit_status == STATUS_FAILED:
                return self._bitstream_failure(
                    project_dir=project_dir,
                    version=version,
                    stdout=stdout,
                    stderr=stderr,
                    top_module=top,
                    run_status=run_status,
                    marker_error=markers.get("BITSTREAM_ERROR"),
                    errors=err_list,
                    warnings=warn_list,
                )

            bit_info = self._resolve_bitstream_info(
                project_dir=project_dir,
                marker_path=markers.get("BITSTREAM_PATH"),
                top_module=top,
            )
            if bit_info is None:
                return self._bitstream_failure(
                    project_dir=project_dir,
                    version=version,
                    stdout=stdout,
                    stderr=stderr,
                    top_module=top,
                    run_status=run_status,
                    marker_error=(
                        markers.get("BITSTREAM_ERROR")
                        or "Bitstream generation finished but .bit file was not found"
                    ),
                    errors=err_list,
                    warnings=warn_list,
                )

            if bit_info["size_bytes"] <= 0:
                return self._bitstream_failure(
                    project_dir=project_dir,
                    version=version,
                    stdout=stdout,
                    stderr=stderr,
                    top_module=top,
                    run_status=run_status,
                    marker_error="Generated bitstream file is empty (0 bytes)",
                    errors=err_list,
                    warnings=warn_list,
                )

            result = BitstreamResult(
                success=True,
                status=STATUS_COMPLETED,
                message="Bitstream generated successfully",
                project_path=str(project_dir),
                top_module=top,
                vivado_version=version,
                log_summary=_trim_output(stdout, stderr, limit=2500),
                errors=err_list,
                warnings=warn_list,
                bitstream=bit_info,
                bitstream_exists=True,
                path=bit_info["path"],
                filename=bit_info["filename"],
                size_bytes=bit_info["size_bytes"],
                extra={
                    "impl_run_status": run_status or None,
                    "progress": markers.get("BITSTREAM_PROGRESS"),
                },
            )
            _write_status(project_dir, result)
            return result
        except VivadoMCPError as exc:
            return _failure(exc)
        except OSError as exc:
            return BitstreamResult(
                success=False,
                status=STATUS_FAILED,
                message=f"Filesystem error during bitstream generation: {exc}",
                error={
                    "type": "BitstreamError",
                    "code": "bitstream_filesystem_error",
                    "message": f"Filesystem error during bitstream generation: {exc}",
                    "status": STATUS_FAILED,
                },
            )

    def get_bitstream_status(self, project_path: str) -> BitstreamResult:
        """Return the current bitstream generation state without launching a run."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            version = self._vivado_version_or_raise()

            script = build_bitstream_status_tcl(xpr_path=xpr_path)
            try:
                result = self.vivado.run_tcl(script, timeout=_STATUS_TIMEOUT_S)
                stdout = result.stdout
                stderr = result.stderr
            except VivadoExecutionError as exc:
                return BitstreamResult(
                    success=False,
                    status=STATUS_UNKNOWN,
                    message=exc.message,
                    project_path=str(project_dir),
                    vivado_version=version,
                    log_summary=_trim_output(exc.stdout, exc.stderr, limit=1500),
                    error={
                        "type": "BitstreamError",
                        "code": "bitstream_error",
                        "message": exc.message,
                        "status": STATUS_UNKNOWN,
                    },
                )

            markers = _parse_markers(stdout)
            marker_status = (markers.get("BITSTREAM_STATUS") or "").lower()
            run_status = markers.get("IMPL_RUN_STATUS") or ""
            top = markers.get("BITSTREAM_TOP")

            bit_info = self._resolve_bitstream_info(
                project_dir=project_dir,
                marker_path=markers.get("BITSTREAM_PATH"),
                top_module=top,
            )
            exists = bit_info is not None and bit_info["size_bytes"] > 0

            if marker_status == STATUS_BLOCKED:
                return BitstreamResult(
                    success=True,
                    status=STATUS_BLOCKED,
                    reason=_BLOCKED_STATUS_REASON,
                    message=_BLOCKED_STATUS_REASON,
                    project_path=str(project_dir),
                    vivado_version=version,
                    bitstream_exists=False,
                    extra={
                        "vivado_status": run_status or None,
                        "progress": markers.get("BITSTREAM_PROGRESS"),
                    },
                )

            status = marker_status or classify_bitstream_run_status(
                run_status,
                bitstream_exists=exists,
            )
            if status not in {
                STATUS_NOT_STARTED,
                STATUS_RUNNING,
                STATUS_COMPLETED,
                STATUS_FAILED,
                STATUS_CANCELLED,
                STATUS_BLOCKED,
                STATUS_UNKNOWN,
            }:
                status = classify_bitstream_run_status(
                    run_status,
                    bitstream_exists=exists,
                )

            # Prefer live evidence of a valid .bit when Vivado reports completed.
            if exists and status in {STATUS_NOT_STARTED, STATUS_UNKNOWN}:
                if "write_bitstream" in run_status.lower() or marker_status == (
                    STATUS_COMPLETED
                ):
                    status = STATUS_COMPLETED

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

            payload = BitstreamResult(
                success=True,
                status=status,
                message=f"Bitstream status: {status}",
                project_path=str(project_dir),
                top_module=top,
                vivado_version=version,
                bitstream_exists=bool(exists),
                path=bit_info["path"] if exists and bit_info else None,
                filename=bit_info["filename"] if exists and bit_info else None,
                size_bytes=bit_info["size_bytes"] if exists and bit_info else None,
                bitstream=bit_info if exists else None,
                reason=(
                    _BLOCKED_STATUS_REASON if status == STATUS_BLOCKED else None
                ),
                extra={
                    "vivado_status": run_status or None,
                    "progress": markers.get("BITSTREAM_PROGRESS"),
                    "synth_run_status": markers.get("SYNTH_RUN_STATUS"),
                },
            )
            return payload
        except VivadoMCPError as exc:
            return _failure(exc)
        except OSError as exc:
            return BitstreamResult(
                success=False,
                status=STATUS_FAILED,
                message=f"Filesystem error while reading bitstream status: {exc}",
                error={
                    "type": "BitstreamError",
                    "code": "bitstream_filesystem_error",
                    "message": (
                        f"Filesystem error while reading bitstream status: {exc}"
                    ),
                    "status": STATUS_FAILED,
                },
            )

    def get_bitstream_path(self, project_path: str) -> BitstreamResult:
        """Return the validated absolute path of the generated ``.bit`` file."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            version = self._vivado_version_or_none()

            # Prefer a live Vivado query when available; fall back to artifacts.
            bit_info: dict[str, Any] | None = None
            try:
                self._vivado_version_or_raise()
                script = build_bitstream_status_tcl(xpr_path=xpr_path)
                result = self.vivado.run_tcl(script, timeout=_STATUS_TIMEOUT_S)
                markers = _parse_markers(result.stdout)
                if (markers.get("BITSTREAM_STATUS") or "").lower() == STATUS_BLOCKED:
                    return BitstreamResult(
                        success=True,
                        status=STATUS_NOT_AVAILABLE,
                        path=None,
                        message="Bitstream is not available",
                        project_path=str(project_dir),
                        vivado_version=version,
                        reason=_BLOCKED_STATUS_REASON,
                    )
                bit_info = self._resolve_bitstream_info(
                    project_dir=project_dir,
                    marker_path=markers.get("BITSTREAM_PATH"),
                    top_module=markers.get("BITSTREAM_TOP"),
                )
            except VivadoMCPError:
                bit_info = self._find_bitstream_on_disk(project_dir)
            except OSError as exc:
                return BitstreamResult(
                    success=False,
                    status=STATUS_FAILED,
                    message=f"Filesystem error while locating bitstream: {exc}",
                    path=None,
                    project_path=str(project_dir),
                    error={
                        "type": "BitstreamError",
                        "code": "bitstream_filesystem_error",
                        "message": (
                            f"Filesystem error while locating bitstream: {exc}"
                        ),
                        "status": STATUS_FAILED,
                    },
                )

            if bit_info is None or bit_info["size_bytes"] <= 0:
                return BitstreamResult(
                    success=True,
                    status=STATUS_NOT_AVAILABLE,
                    path=None,
                    message="Bitstream is not available",
                    project_path=str(project_dir),
                    vivado_version=version,
                )

            return BitstreamResult(
                success=True,
                status=STATUS_AVAILABLE,
                message="Bitstream is available",
                project_path=str(project_dir),
                vivado_version=version,
                path=bit_info["path"],
                filename=bit_info["filename"],
                size_bytes=bit_info["size_bytes"],
                bitstream=bit_info,
                bitstream_exists=True,
            )
        except VivadoMCPError as exc:
            return _failure(exc)
        except OSError as exc:
            return BitstreamResult(
                success=False,
                status=STATUS_FAILED,
                message=f"Filesystem error while locating bitstream: {exc}",
                path=None,
                error={
                    "type": "BitstreamError",
                    "code": "bitstream_filesystem_error",
                    "message": f"Filesystem error while locating bitstream: {exc}",
                    "status": STATUS_FAILED,
                },
            )

    def _bitstream_failure(
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
    ) -> BitstreamResult:
        markers = _parse_markers(stdout)
        if errors is None or warnings is None:
            err_list, warn_list = self._parser.extract_errors_warnings(
                "\n".join(part for part in (stdout, stderr) if part)
            )
            errors = errors if errors is not None else err_list
            warnings = warnings if warnings is not None else warn_list

        status = STATUS_FAILED
        marker_status = (markers.get("BITSTREAM_STATUS") or "").lower()
        if marker_status == STATUS_BLOCKED:
            status = STATUS_BLOCKED
        elif marker_status == STATUS_CANCELLED:
            status = STATUS_CANCELLED

        message = (
            marker_error
            or markers.get("BITSTREAM_ERROR")
            or "Bitstream generation failed"
        )
        if errors and not marker_error and status == STATUS_FAILED:
            message = errors[0]

        result = BitstreamResult(
            success=False,
            status=status,
            message=message,
            reason=message if status == STATUS_BLOCKED else None,
            project_path=str(project_dir),
            top_module=top_module or markers.get("BITSTREAM_TOP"),
            vivado_version=version,
            log_summary=_trim_output(stdout, stderr, limit=2500),
            errors=errors or [],
            warnings=warnings or [],
            error={
                "type": "BitstreamError",
                "code": "bitstream_error",
                "message": message,
                "status": status,
            },
            extra={
                "impl_run_status": run_status or markers.get("IMPL_RUN_STATUS"),
            },
        )
        _write_status(project_dir, result)
        return result

    def _resolve_bitstream_info(
        self,
        *,
        project_dir: Path,
        marker_path: str | None,
        top_module: str | None,
    ) -> dict[str, Any] | None:
        candidates: list[Path] = []
        if marker_path:
            candidates.append(Path(marker_path))
        candidates.extend(self._candidate_bit_paths(project_dir, top_module))

        seen: set[Path] = set()
        for candidate in candidates:
            try:
                key = candidate.resolve() if candidate.exists() else candidate
            except OSError:
                key = candidate
            if key in seen:
                continue
            seen.add(key)
            validated = _validate_bitstream_path(project_dir, candidate)
            if validated is not None:
                return validated
        return None

    def _find_bitstream_on_disk(self, project_dir: Path) -> dict[str, Any] | None:
        last = _load_status(project_dir)
        if last:
            bit = last.get("bitstream")
            if isinstance(bit, dict) and isinstance(bit.get("path"), str):
                validated = _validate_bitstream_path(project_dir, Path(bit["path"]))
                if validated is not None:
                    return validated
            if isinstance(last.get("path"), str):
                validated = _validate_bitstream_path(project_dir, Path(last["path"]))
                if validated is not None:
                    return validated
        return self._resolve_bitstream_info(
            project_dir=project_dir,
            marker_path=None,
            top_module=None,
        )

    def _candidate_bit_paths(
        self,
        project_dir: Path,
        top_module: str | None,
    ) -> list[Path]:
        candidates: list[Path] = []
        runs_dirs = list(project_dir.glob("*.runs"))
        for runs_dir in runs_dirs:
            impl_dir = runs_dir / "impl_1"
            if top_module:
                candidates.append(impl_dir / f"{top_module}.bit")
            if impl_dir.is_dir():
                try:
                    candidates.extend(sorted(impl_dir.glob("*.bit")))
                except OSError:
                    pass
        return candidates

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


def _validate_bitstream_path(
    project_dir: Path,
    candidate: Path,
) -> dict[str, Any] | None:
    """Validate that ``candidate`` is a non-empty ``.bit`` under the project.

    Rejects path traversal outside the project directory and non-regular files.
    """
    try:
        project_root = project_dir.resolve()
        resolved = candidate.expanduser()
        if not resolved.is_absolute():
            resolved = (project_dir / resolved).resolve()
        else:
            resolved = resolved.resolve()
    except (OSError, RuntimeError):
        return None

    try:
        resolved.relative_to(project_root)
    except ValueError:
        logger.info(
            "Rejected bitstream path outside project tree: %s", resolved
        )
        return None

    # Prefer files under a Vivado runs/impl_1 area when present.
    parts_lower = [part.lower() for part in resolved.parts]
    under_runs = any(part.endswith(".runs") for part in parts_lower)
    if under_runs and "impl_1" not in parts_lower:
        # Still allow if it is clearly a .bit under the project runs tree.
        if resolved.suffix.lower() != ".bit":
            return None

    if resolved.suffix.lower() != ".bit":
        return None

    try:
        if not resolved.is_file():
            return None
        size = resolved.stat().st_size
    except OSError:
        return None

    return {
        "path": str(resolved),
        "filename": resolved.name,
        "size_bytes": int(size),
    }


def _status_path(project_dir: Path) -> Path:
    return project_dir / _ARTIFACT_DIR / _STATUS_FILE


def _write_status(project_dir: Path, result: BitstreamResult) -> None:
    path = _status_path(project_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write bitstream status artifact: %s", exc)


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


def _failure(exc: VivadoMCPError) -> BitstreamResult:
    logger.info("Bitstream operation failed: %s (%s)", exc.code, exc.message)
    status = STATUS_FAILED
    if isinstance(exc, BitstreamError):
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
    elif isinstance(exc, BitstreamError):
        log_summary = _trim_output(exc.stdout, exc.stderr) or None
        if log_summary:
            error["vivado_output"] = log_summary

    return BitstreamResult(
        success=False,
        status=status,
        message=exc.message,
        log_summary=log_summary,
        error=error,
    )
