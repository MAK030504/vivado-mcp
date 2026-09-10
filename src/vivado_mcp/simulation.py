"""RTL simulation management for Vivado projects.

Creates testbench files under a project-controlled ``sim/`` directory and runs
behavioral simulation through controlled Vivado batch Tcl (XSim). Never
exposes arbitrary shell or Tcl execution to MCP clients.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from vivado_mcp.errors import (
    InvalidSourceError,
    InvalidTopModuleError,
    NoSimulationSourcesError,
    SimulationError,
    SourceAlreadyExistsError,
    VivadoExecutionError,
    VivadoMCPError,
    VivadoNotFoundError,
)
from vivado_mcp.projects import resolve_xpr_path
from vivado_mcp.sources import normalize_language, resolve_rtl_filename
from vivado_mcp.tcl import (
    build_run_simulation_tcl,
    validate_simulation_time,
    validate_top_module,
)
from vivado_mcp.vivado import Vivado

logger = logging.getLogger(__name__)

_MARKER_PATTERN = re.compile(r"^VIVADO_MCP_([A-Z0-9_]+)=(.*)$", re.MULTILINE)
_STATUS_FILENAME = "last_simulation.json"
_ARTIFACT_DIRNAME = ".vivado_mcp"

# Status values useful for AI-assisted RTL debugging.
STATUS_PASSED = "passed"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_COMPILE_ERROR = "compile_error"
STATUS_ELABORATE_ERROR = "elaborate_error"
STATUS_RUNTIME_ERROR = "runtime_error"
STATUS_ASSERTION_FAILED = "assertion_failed"
STATUS_NO_SOURCES = "no_sources"
STATUS_NOT_RUN = "not_run"


@dataclass(frozen=True, slots=True)
class TestbenchFileInfo:
    """Metadata for a created testbench file."""

    path: str
    language: str
    type: str = "testbench"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Structured result for simulation / testbench operations."""

    success: bool
    status: str | None = None
    project_path: str | None = None
    file: TestbenchFileInfo | None = None
    top_module: str | None = None
    simulation_time: str | None = None
    errors: int | None = None
    warnings: int | None = None
    output: str | None = None
    vivado_version: str | None = None
    message: str | None = None
    ran: bool | None = None
    error: dict[str, str] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"success": self.success}
        if self.status is not None:
            payload["status"] = self.status
        if self.ran is not None:
            payload["ran"] = self.ran
        if self.project_path is not None:
            payload["project_path"] = self.project_path
        if self.file is not None:
            payload["file"] = self.file.to_dict()
        if self.top_module is not None:
            payload["top_module"] = self.top_module
        if self.simulation_time is not None:
            payload["simulation_time"] = self.simulation_time
        if self.errors is not None:
            payload["errors"] = self.errors
        if self.warnings is not None:
            payload["warnings"] = self.warnings
        if self.output is not None:
            payload["output"] = self.output
        if self.vivado_version is not None:
            payload["vivado_version"] = self.vivado_version
        if self.message is not None:
            payload["message"] = self.message
        if self.error is not None:
            payload["error"] = self.error
        for key, value in self.extra.items():
            if key not in payload:
                payload[key] = value
        return payload


class SimulationManager:
    """Create testbenches and run RTL behavioral simulation."""

    def __init__(self, vivado: Vivado | None = None) -> None:
        self.vivado = vivado or Vivado()

    def create_testbench(
        self,
        project_path: str,
        filename: str,
        code: str,
        language: str = "verilog",
    ) -> SimulationResult:
        """Create a ``.v`` / ``.sv`` testbench under the project's ``sim/`` dir.

        Does not add the file to the Vivado project — call ``add_source`` with
        ``fileset='sim_1'`` next. Never executes ``code``. Existing files are
        not overwritten.
        """
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            lang = normalize_language(language)
            safe_name = resolve_rtl_filename(filename, lang)
            sim_dir = project_dir / "sim"
            target = (sim_dir / safe_name).resolve()
            _ensure_inside_directory(target, sim_dir.resolve())

            if target.exists():
                raise SourceAlreadyExistsError(
                    f"Testbench file already exists: {target}. "
                    "Refusing to overwrite. Choose a new filename."
                )
            if "\x00" in code:
                raise InvalidSourceError("Testbench code contains a null byte.")

            sim_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8", newline="\n")

            return SimulationResult(
                success=True,
                project_path=str(project_dir),
                file=TestbenchFileInfo(
                    path=str(target),
                    language=lang,
                    type="testbench",
                ),
                message=f"Created testbench file '{safe_name}'.",
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def run_simulation(
        self,
        project_path: str,
        top_module: str | None = None,
        simulation_time: str = "100ns",
    ) -> SimulationResult:
        """Run RTL behavioral simulation with Vivado XSim in batch mode."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            sim_time = validate_simulation_time(simulation_time)
            top: str | None = None
            if top_module is not None and str(top_module).strip():
                top = validate_top_module(str(top_module))

            version = self._vivado_version_or_raise()
            script = build_run_simulation_tcl(
                xpr_path=xpr_path,
                simulation_time=sim_time,
                top_module=top,
            )

            stdout = ""
            stderr = ""
            try:
                result = self.vivado.run_tcl(script, timeout=900.0)
                stdout = result.stdout
                stderr = result.stderr
            except VivadoExecutionError as exc:
                stdout = exc.stdout
                stderr = exc.stderr
                parsed = parse_simulation_output(
                    stdout,
                    stderr,
                    top_module=top,
                    simulation_time=sim_time,
                )
                if parsed.status == STATUS_NO_SOURCES:
                    raise NoSimulationSourcesError(
                        parsed.message
                        or "No simulation sources found in fileset sim_1. "
                        "Create a testbench and add it with add_source(..., fileset='sim_1')."
                    ) from exc
                sim_result = SimulationResult(
                    success=False,
                    status=parsed.status,
                    project_path=str(project_dir),
                    top_module=parsed.top_module or top,
                    simulation_time=sim_time,
                    errors=parsed.errors,
                    warnings=parsed.warnings,
                    output=parsed.output,
                    vivado_version=version,
                    message=parsed.message,
                    ran=True,
                    error={
                        "type": "SimulationError",
                        "code": "simulation_error",
                        "message": parsed.message
                        or "Vivado simulation failed.",
                        "status": parsed.status,
                    },
                )
                _write_status(project_dir, sim_result)
                return sim_result

            markers = _parse_markers(stdout)
            if markers.get("SIM_STATUS") == STATUS_NO_SOURCES:
                raise NoSimulationSourcesError(
                    markers.get("SIM_ERROR")
                    or "No simulation sources found in fileset sim_1."
                )

            parsed = parse_simulation_output(
                stdout,
                stderr,
                top_module=top or markers.get("SIM_TOP"),
                simulation_time=sim_time,
            )
            success = parsed.status in {STATUS_PASSED, STATUS_COMPLETED}
            sim_result = SimulationResult(
                success=success,
                status=parsed.status if success else parsed.status,
                project_path=str(project_dir),
                top_module=parsed.top_module,
                simulation_time=sim_time,
                errors=parsed.errors,
                warnings=parsed.warnings,
                output=parsed.output,
                vivado_version=version,
                message=parsed.message,
                ran=True,
                error=None
                if success
                else {
                    "type": "SimulationError",
                    "code": "simulation_error",
                    "message": parsed.message or "Simulation did not pass.",
                    "status": parsed.status,
                },
            )
            # Normalize successful status wording for MCP clients.
            if success:
                sim_result = SimulationResult(
                    success=True,
                    status=STATUS_COMPLETED
                    if parsed.status == STATUS_PASSED
                    else parsed.status,
                    project_path=str(project_dir),
                    top_module=parsed.top_module,
                    simulation_time=sim_time,
                    errors=parsed.errors,
                    warnings=parsed.warnings,
                    output=parsed.output,
                    vivado_version=version,
                    message=parsed.message or "Simulation completed.",
                    ran=True,
                )
            _write_status(project_dir, sim_result)
            return sim_result
        except VivadoMCPError as exc:
            return _failure(exc, ran=True if isinstance(exc, SimulationError) else None)

    def get_simulation_status(self, project_path: str) -> SimulationResult:
        """Return structured info about the most recent simulation run."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            status_path = _status_path(project_dir)
            if not status_path.is_file():
                return SimulationResult(
                    success=True,
                    status=STATUS_NOT_RUN,
                    ran=False,
                    project_path=str(project_dir),
                    errors=0,
                    warnings=0,
                    message=(
                        "No simulation has been run for this project yet. "
                        "Call run_simulation first."
                    ),
                )

            raw = json.loads(status_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise SimulationError(
                    "Stored simulation status is corrupt.",
                    status=STATUS_FAILED,
                )
            return SimulationResult(
                success=bool(raw.get("success", False)),
                status=str(raw.get("status") or STATUS_FAILED),
                ran=bool(raw.get("ran", True)),
                project_path=str(raw.get("project_path") or project_dir),
                top_module=raw.get("top_module"),
                simulation_time=raw.get("simulation_time"),
                errors=int(raw["errors"]) if raw.get("errors") is not None else None,
                warnings=(
                    int(raw["warnings"]) if raw.get("warnings") is not None else None
                ),
                output=raw.get("output"),
                vivado_version=raw.get("vivado_version"),
                message=raw.get("message"),
                error=raw.get("error"),
            )
        except VivadoMCPError as exc:
            return _failure(exc)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return _failure(
                SimulationError(
                    f"Failed to read simulation status: {exc}",
                    status=STATUS_FAILED,
                )
            )

    def _vivado_version_or_raise(self) -> str | None:
        info = self.vivado.get_version()
        if not info.installed:
            raise VivadoNotFoundError(
                info.message
                or "Vivado was not found. Set VIVADO_PATH to vivado.bat / vivado."
            )
        return info.version


@dataclass(frozen=True, slots=True)
class _ParsedSimulation:
    status: str
    top_module: str | None
    errors: int
    warnings: int
    output: str
    message: str


def parse_simulation_output(
    stdout: str,
    stderr: str = "",
    *,
    top_module: str | None = None,
    simulation_time: str | None = None,
) -> _ParsedSimulation:
    """Classify Vivado simulation stdout/stderr into a structured status."""
    markers = _parse_markers(stdout)
    combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    trimmed = _trim_output(stdout, stderr)
    errors = _count_errors(combined)
    warnings = _count_warnings(combined)
    top = markers.get("SIM_TOP") or top_module
    marker_status = markers.get("SIM_STATUS", "").strip().lower()
    marker_error = markers.get("SIM_ERROR", "").strip()

    status = classify_simulation_status(
        combined,
        marker_status=marker_status,
        marker_error=marker_error,
    )

    if status == STATUS_NO_SOURCES:
        message = marker_error or "No simulation sources in fileset sim_1."
    elif status == STATUS_PASSED:
        message = "Simulation passed."
    elif status == STATUS_COMPILE_ERROR:
        message = marker_error or "HDL compilation failed."
    elif status == STATUS_ELABORATE_ERROR:
        message = marker_error or "Elaboration failed."
    elif status == STATUS_ASSERTION_FAILED:
        message = marker_error or "Testbench assertion failed."
    elif status == STATUS_RUNTIME_ERROR:
        message = marker_error or "Simulation runtime error."
    elif status in {STATUS_FAILED, STATUS_COMPLETED}:
        message = marker_error or (
            "Simulation completed." if status == STATUS_COMPLETED else "Simulation failed."
        )
    else:
        message = marker_error or f"Simulation status: {status}."

    if simulation_time and "simulation_time" not in message.lower():
        pass  # keep message concise

    return _ParsedSimulation(
        status=status,
        top_module=top,
        errors=errors,
        warnings=warnings,
        output=trimmed,
        message=message,
    )


def classify_simulation_status(
    text: str,
    *,
    marker_status: str = "",
    marker_error: str = "",
) -> str:
    """Map Vivado log text to a discrete simulation status.

    Explicit MCP markers win over heuristic log scraping. Vivado often emits
    ``WARNING: [VRFC ...]`` (for example missing timescale) even on a clean
    pass; those must not override ``VIVADO_MCP_SIM_STATUS=passed``.
    """
    lowered = text.lower()
    err_lower = marker_error.lower()
    combined = f"{lowered}\n{err_lower}"

    if marker_status == STATUS_NO_SOURCES or "no simulation sources" in combined:
        return STATUS_NO_SOURCES

    # Explicit success markers always win (ignore WARNING noise such as VRFC).
    if marker_status in {STATUS_PASSED, STATUS_COMPLETED}:
        return STATUS_PASSED

    # Specific failure markers from our Tcl already carry the right status.
    if marker_status in {
        STATUS_COMPILE_ERROR,
        STATUS_ELABORATE_ERROR,
        STATUS_RUNTIME_ERROR,
        STATUS_ASSERTION_FAILED,
    }:
        return marker_status

    # Refine generic failures (or missing markers) from Vivado log text.
    if _looks_like_assertion_failure(combined):
        return STATUS_ASSERTION_FAILED

    if _looks_like_compile_error(combined):
        return STATUS_COMPILE_ERROR

    if _looks_like_elaborate_error(combined):
        return STATUS_ELABORATE_ERROR

    if _looks_like_runtime_error(combined):
        return STATUS_RUNTIME_ERROR

    if "error:" in combined or re.search(r"(?m)^\s*error(?:\s*:|\s+\[)", combined):
        return STATUS_FAILED

    if marker_status == STATUS_FAILED:
        return STATUS_FAILED

    if "vivado_mcp_status=ok" in combined:
        return STATUS_PASSED

    return STATUS_FAILED


def _looks_like_assertion_failure(text: str) -> bool:
    patterns = (
        r"assertion\s+failed",
        r"\$fatal",
        r"(?m)^\s*error(?:\s*:|\s+\[).*\$error",
        r"error:\s+assertion",
    )
    return any(re.search(pat, text) for pat in patterns)


def _looks_like_compile_error(text: str) -> bool:
    # Match ERROR-level compile diagnostics only — not WARNING: [VRFC ...].
    patterns = (
        r"(?m)^\s*error(?:\s*:|\s+\[).*\[vrfc\b",
        r"(?m)^\s*error(?:\s*:|\s+\[).*syntax error",
        r"compile\s+error",
        r"error while parsing",
        r"unexpected token",
        r"(?m)^\s*error(?:\s*:|\s+\[).*module\s+\w+\s+is not defined",
    )
    return any(re.search(pat, text) for pat in patterns)


def _looks_like_elaborate_error(text: str) -> bool:
    patterns = (
        r"elaborat\w*\s+error",
        r"static elaboration",
        r"\[xsim\s+43-",
        r"failed to elaborate",
        r"elaboration failed",
    )
    return any(re.search(pat, text) for pat in patterns)


def _looks_like_runtime_error(text: str) -> bool:
    patterns = (
        r"fatal error",
        r"simulation aborted",
        r"runtime error",
        r"\$finish called",  # not always an error; exclude below
    )
    if re.search(r"\$finish", text) and "fatal" not in text and "error:" not in text:
        return False
    return any(re.search(pat, text) for pat in patterns if pat != r"\$finish called")


def _count_errors(text: str) -> int:
    return len(re.findall(r"(?im)^\s*error(?:\s*:|\s+\[)", text))


def _count_warnings(text: str) -> int:
    return len(re.findall(r"(?im)^\s*warning(?:\s*:|\s+\[)", text))


def _status_path(project_dir: Path) -> Path:
    return project_dir / _ARTIFACT_DIRNAME / _STATUS_FILENAME


def _write_status(project_dir: Path, result: SimulationResult) -> None:
    path = _status_path(project_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = result.to_dict()
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write simulation status artifact: %s", exc)


def _ensure_inside_directory(path: Path, directory: Path) -> None:
    try:
        path.relative_to(directory)
    except ValueError as exc:
        raise InvalidSourceError(
            f"Refusing to write outside the project sim directory: {path}"
        ) from exc


def _parse_markers(stdout: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2).strip()
        for match in _MARKER_PATTERN.finditer(stdout)
    }


def _trim_output(stdout: str, stderr: str, *, limit: int = 6000) -> str:
    combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    if len(combined) <= limit:
        return combined
    return combined[: limit - 20] + "\n...[truncated]..."


def _failure(
    exc: VivadoMCPError,
    *,
    ran: bool | None = None,
) -> SimulationResult:
    logger.info("Simulation operation failed: %s (%s)", exc.code, exc.message)
    status = STATUS_FAILED
    if isinstance(exc, SimulationError):
        status = exc.status
    elif isinstance(exc, NoSimulationSourcesError):
        status = STATUS_NO_SOURCES
    elif isinstance(exc, (InvalidTopModuleError, InvalidSourceError)):
        status = STATUS_FAILED

    error: dict[str, str] = {
        "type": type(exc).__name__,
        "code": exc.code,
        "message": exc.message,
    }
    output = None
    if isinstance(exc, VivadoExecutionError):
        output = _trim_output(exc.stdout, exc.stderr)
        if output:
            error["vivado_output"] = output
    elif isinstance(exc, SimulationError):
        output = _trim_output(exc.stdout, exc.stderr) or None
        if output:
            error["vivado_output"] = output

    return SimulationResult(
        success=False,
        status=status,
        ran=ran,
        output=output,
        error=error,
        message=exc.message,
    )
