"""Vivado project management (create / open / close).

This layer sits between MCP tools and the Vivado executable abstraction.
It builds controlled Tcl scripts and never exposes arbitrary shell/Tcl
execution to MCP clients.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from vivado_mcp.errors import (
    InvalidProjectPathError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    VivadoExecutionError,
    VivadoMCPError,
    VivadoNotFoundError,
)
from vivado_mcp.tcl import (
    build_close_project_tcl,
    build_create_project_tcl,
    build_open_project_tcl,
    normalize_user_path,
    validate_part,
    validate_project_name,
)
from vivado_mcp.vivado import Vivado

logger = logging.getLogger(__name__)

_MARKER_PATTERN = re.compile(r"^VIVADO_MCP_([A-Z0-9_]+)=(.*)$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    """Structured project metadata returned to MCP clients."""

    name: str
    path: str
    part: str | None = None
    xpr: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProjectOperationResult:
    """Structured result for create/open/close operations."""

    success: bool
    project: ProjectInfo | None = None
    vivado_version: str | None = None
    message: str | None = None
    vivado_output: str | None = None
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"success": self.success}
        if self.project is not None:
            payload["project"] = self.project.to_dict()
        if self.vivado_version is not None:
            payload["vivado_version"] = self.vivado_version
        if self.message is not None:
            payload["message"] = self.message
        if self.vivado_output is not None:
            payload["vivado_output"] = self.vivado_output
        if self.error is not None:
            payload["error"] = self.error
        return payload


class ProjectManager:
    """Create, open, and close Vivado projects via batch Tcl."""

    def __init__(self, vivado: Vivado | None = None) -> None:
        self.vivado = vivado or Vivado()

    def create_project(self, name: str, path: str, part: str) -> ProjectOperationResult:
        """Create a new Vivado project under ``path`` / ``name``.

        ``path`` is the parent directory. The project is created at
        ``{path}/{name}/{name}.xpr``. Existing projects are never overwritten.
        """
        try:
            project_name = validate_project_name(name)
            parent = normalize_user_path(path)
            part_id = validate_part(part)
            project_dir = parent / project_name
            xpr_path = project_dir / f"{project_name}.xpr"

            if xpr_path.exists() or (
                project_dir.exists() and any(project_dir.glob("*.xpr"))
            ):
                raise ProjectAlreadyExistsError(
                    f"A Vivado project already exists at {project_dir}. "
                    "Refusing to overwrite. Choose a new name or path."
                )

            parent.mkdir(parents=True, exist_ok=True)

            version = self._vivado_version_or_raise()
            script = build_create_project_tcl(
                name=project_name,
                parent_dir=parent,
                part=part_id,
            )
            result = self.vivado.run_tcl(script, timeout=300.0)
            markers = _parse_markers(result.stdout)
            resolved_dir = markers.get("PROJECT_DIR") or str(project_dir)
            resolved_name = markers.get("PROJECT_NAME") or project_name
            resolved_part = markers.get("PROJECT_PART") or part_id
            resolved_xpr = Path(resolved_dir) / f"{resolved_name}.xpr"
            if not resolved_xpr.exists() and xpr_path.exists():
                resolved_xpr = xpr_path

            if markers.get("STATUS") != "OK" and not resolved_xpr.exists():
                raise VivadoExecutionError(
                    "Vivado did not create the project .xpr file.",
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )

            return ProjectOperationResult(
                success=True,
                project=ProjectInfo(
                    name=resolved_name,
                    path=str(Path(resolved_dir)),
                    part=resolved_part,
                    xpr=str(resolved_xpr),
                ),
                vivado_version=version,
                message=f"Created Vivado project '{resolved_name}'.",
                vivado_output=_trim_output(result.stdout, result.stderr),
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def open_project(self, path: str) -> ProjectOperationResult:
        """Open an existing Vivado project (.xpr) in batch mode and verify it."""
        try:
            xpr_path = resolve_xpr_path(path)
            version = self._vivado_version_or_raise()
            script = build_open_project_tcl(xpr_path=xpr_path)
            result = self.vivado.run_tcl(script, timeout=300.0)
            markers = _parse_markers(result.stdout)
            if markers.get("STATUS") != "OK":
                raise VivadoExecutionError(
                    "Vivado opened the project but did not report success.",
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            project_dir = markers.get("PROJECT_DIR") or str(xpr_path.parent)
            project_name = markers.get("PROJECT_NAME") or xpr_path.stem
            part = markers.get("PROJECT_PART")
            return ProjectOperationResult(
                success=True,
                project=ProjectInfo(
                    name=project_name,
                    path=project_dir,
                    part=part,
                    xpr=str(xpr_path),
                ),
                vivado_version=version,
                message=f"Opened Vivado project '{project_name}'.",
                vivado_output=_trim_output(result.stdout, result.stderr),
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def close_project(self, path: str) -> ProjectOperationResult:
        """Open then close a Vivado project cleanly in batch mode."""
        try:
            xpr_path = resolve_xpr_path(path)
            version = self._vivado_version_or_raise()
            script = build_close_project_tcl(xpr_path=xpr_path)
            result = self.vivado.run_tcl(script, timeout=300.0)
            markers = _parse_markers(result.stdout)
            if markers.get("STATUS") != "OK" and markers.get("CLOSED") != "1":
                raise VivadoExecutionError(
                    "Vivado did not confirm that the project was closed.",
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            return ProjectOperationResult(
                success=True,
                project=ProjectInfo(
                    name=xpr_path.stem,
                    path=str(xpr_path.parent),
                    part=None,
                    xpr=str(xpr_path),
                ),
                vivado_version=version,
                message=f"Closed Vivado project '{xpr_path.stem}'.",
                vivado_output=_trim_output(result.stdout, result.stderr),
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def _vivado_version_or_raise(self) -> str | None:
        info = self.vivado.get_version()
        if not info.installed:
            raise VivadoNotFoundError(
                info.message
                or "Vivado was not found. Set VIVADO_PATH to vivado.bat / vivado."
            )
        return info.version


def resolve_xpr_path(path: str | Path) -> Path:
    """Resolve a user path to an existing ``.xpr`` file.

    Accepts either the ``.xpr`` file itself or a project directory that
    contains exactly one ``.xpr`` (or ``<dirname>.xpr``).
    """
    candidate = normalize_user_path(path)
    if candidate.suffix.lower() == ".xpr":
        if not candidate.is_file():
            raise ProjectNotFoundError(f"Vivado project file not found: {candidate}")
        return candidate

    if candidate.is_file():
        raise InvalidProjectPathError(
            f"Expected a .xpr file or project directory, got a file: {candidate}"
        )

    if not candidate.exists():
        raise ProjectNotFoundError(f"Vivado project path not found: {candidate}")

    if not candidate.is_dir():
        raise InvalidProjectPathError(f"Invalid Vivado project path: {candidate}")

    preferred = candidate / f"{candidate.name}.xpr"
    if preferred.is_file():
        return preferred

    xprs = sorted(candidate.glob("*.xpr"))
    if not xprs:
        raise ProjectNotFoundError(
            f"No .xpr file found in project directory: {candidate}"
        )
    if len(xprs) > 1:
        raise InvalidProjectPathError(
            f"Multiple .xpr files found in {candidate}: "
            + ", ".join(item.name for item in xprs)
            + ". Pass the full path to the .xpr file."
        )
    return xprs[0]


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


def _failure(exc: VivadoMCPError) -> ProjectOperationResult:
    logger.info("Project operation failed: %s (%s)", exc.code, exc.message)
    error: dict[str, str] = {
        "type": type(exc).__name__,
        "code": exc.code,
        "message": exc.message,
    }
    if isinstance(exc, VivadoExecutionError):
        detail = _trim_output(exc.stdout, exc.stderr)
        if detail:
            error["vivado_output"] = detail
    return ProjectOperationResult(success=False, error=error)
