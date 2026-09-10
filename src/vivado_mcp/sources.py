"""RTL / source-file management for Vivado projects.

Creates Verilog/SystemVerilog files under a project-controlled ``rtl/``
directory and adds/removes/lists them through controlled Vivado batch Tcl.
Never exposes arbitrary shell or Tcl execution to MCP clients.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from vivado_mcp.errors import (
    InvalidSourceError,
    SourceAlreadyExistsError,
    SourceNotFoundError,
    VivadoExecutionError,
    VivadoMCPError,
    VivadoNotFoundError,
)
from vivado_mcp.projects import resolve_xpr_path
from vivado_mcp.tcl import (
    build_add_source_tcl,
    build_list_sources_tcl,
    build_remove_source_tcl,
    normalize_user_path,
)
from vivado_mcp.vivado import Vivado

logger = logging.getLogger(__name__)

_MARKER_PATTERN = re.compile(r"^VIVADO_MCP_([A-Z0-9_]+)=(.*)$", re.MULTILINE)
_FILENAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")

_LANGUAGE_EXTENSIONS = {
    "verilog": ".v",
    "systemverilog": ".sv",
}
_EXTENSION_LANGUAGES = {
    ".v": "verilog",
    ".sv": "systemverilog",
}
_VIVADO_FILE_TYPE_MAP = {
    "verilog": "verilog",
    "systemverilog": "systemverilog",
    "verilog header": "verilog",
    "systemverilog header": "systemverilog",
}


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """One RTL source entry."""

    path: str
    type: str
    library: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceOperationResult:
    """Structured result for RTL/source operations."""

    success: bool
    project_path: str | None = None
    source_path: str | None = None
    language: str | None = None
    sources: list[SourceInfo] | None = None
    vivado_version: str | None = None
    message: str | None = None
    vivado_output: str | None = None
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"success": self.success}
        if self.project_path is not None:
            payload["project_path"] = self.project_path
            payload["project"] = self.project_path
        if self.source_path is not None:
            payload["source_path"] = self.source_path
            payload["source"] = self.source_path
        if self.language is not None:
            payload["language"] = self.language
        if self.sources is not None:
            payload["sources"] = [item.to_dict() for item in self.sources]
        if self.vivado_version is not None:
            payload["vivado_version"] = self.vivado_version
        if self.message is not None:
            payload["message"] = self.message
        if self.vivado_output is not None:
            payload["vivado_output"] = self.vivado_output
        if self.error is not None:
            payload["error"] = self.error
        return payload


class SourceManager:
    """Create, add, remove, and list RTL sources for a Vivado project."""

    def __init__(self, vivado: Vivado | None = None) -> None:
        self.vivado = vivado or Vivado()

    def create_rtl_file(
        self,
        project_path: str,
        filename: str,
        code: str,
        language: str = "verilog",
    ) -> SourceOperationResult:
        """Create a ``.v`` / ``.sv`` file under the project's ``rtl/`` directory.

        Does not add the file to the Vivado project — call ``add_source`` next.
        Never executes or interprets ``code``. Existing files are not overwritten.
        """
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            lang = normalize_language(language)
            safe_name = resolve_rtl_filename(filename, lang)
            rtl_dir = project_dir / "rtl"
            target = (rtl_dir / safe_name).resolve()
            _ensure_inside_directory(target, rtl_dir.resolve())

            if target.exists():
                raise SourceAlreadyExistsError(
                    f"RTL file already exists: {target}. "
                    "Refusing to overwrite. Choose a new filename."
                )
            if "\x00" in code:
                raise InvalidSourceError("RTL code contains a null byte.")

            rtl_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8", newline="\n")

            return SourceOperationResult(
                success=True,
                project_path=str(project_dir),
                source_path=str(target),
                language=lang,
                message=f"Created RTL file '{safe_name}'.",
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def add_source(
        self,
        project_path: str,
        source_path: str,
        fileset: str = "sources_1",
    ) -> SourceOperationResult:
        """Add an existing ``.v`` / ``.sv`` file to ``sources_1`` or ``sim_1``."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            source = normalize_user_path(source_path)
            if not source.is_file():
                raise SourceNotFoundError(f"Source file not found: {source}")
            lang = language_from_path(source)

            version = self._vivado_version_or_raise()
            script = build_add_source_tcl(
                xpr_path=xpr_path,
                source_path=source,
                fileset=fileset,
            )
            result = self.vivado.run_tcl(script, timeout=300.0)
            markers = _parse_markers(result.stdout)
            if markers.get("STATUS") != "OK":
                raise VivadoExecutionError(
                    "Vivado did not confirm that the source was added.",
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            fileset_name = markers.get("FILESET") or fileset.strip()

            return SourceOperationResult(
                success=True,
                project_path=str(project_dir),
                source_path=str(source),
                language=lang,
                vivado_version=version,
                message=(
                    f"Added source '{source.name}' to fileset '{fileset_name}'."
                ),
                vivado_output=_trim_output(result.stdout, result.stderr),
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def remove_source(
        self, project_path: str, source_path: str
    ) -> SourceOperationResult:
        """Remove a source from the Vivado project without deleting the file."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            source = normalize_user_path(source_path)
            if not source.is_file():
                raise SourceNotFoundError(f"Source file not found: {source}")
            lang = language_from_path(source)

            version = self._vivado_version_or_raise()
            script = build_remove_source_tcl(xpr_path=xpr_path, source_path=source)
            try:
                result = self.vivado.run_tcl(script, timeout=300.0)
            except VivadoExecutionError as exc:
                markers = _parse_markers(exc.stdout)
                if markers.get("ERROR") == "SOURCE_NOT_IN_PROJECT":
                    raise SourceNotFoundError(
                        f"Source is not associated with the Vivado project: {source}"
                    ) from exc
                raise

            markers = _parse_markers(result.stdout)
            if markers.get("STATUS") != "OK" and markers.get("REMOVED") != "1":
                raise VivadoExecutionError(
                    "Vivado did not confirm that the source was removed.",
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )

            return SourceOperationResult(
                success=True,
                project_path=str(project_dir),
                source_path=str(source),
                language=lang,
                vivado_version=version,
                message=(
                    f"Removed source '{source.name}' from the project "
                    "(physical file was not deleted)."
                ),
                vivado_output=_trim_output(result.stdout, result.stderr),
            )
        except VivadoMCPError as exc:
            return _failure(exc)

    def list_sources(self, project_path: str) -> SourceOperationResult:
        """List design sources in the Vivado project."""
        try:
            xpr_path = resolve_xpr_path(project_path)
            project_dir = xpr_path.parent
            version = self._vivado_version_or_raise()
            script = build_list_sources_tcl(xpr_path=xpr_path)
            result = self.vivado.run_tcl(script, timeout=300.0)
            markers = _parse_markers(result.stdout)
            if markers.get("STATUS") != "OK":
                raise VivadoExecutionError(
                    "Vivado did not confirm source listing.",
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            sources = parse_source_list(result.stdout)
            return SourceOperationResult(
                success=True,
                project_path=str(project_dir),
                sources=sources,
                vivado_version=version,
                message=f"Listed {len(sources)} source file(s).",
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


def normalize_language(language: str) -> str:
    """Normalize and validate a language identifier."""
    cleaned = language.strip().lower()
    if cleaned in {"verilog", "v"}:
        return "verilog"
    if cleaned in {"systemverilog", "sv"}:
        return "systemverilog"
    raise InvalidSourceError(
        f"Unsupported language {language!r}. Use 'verilog' or 'systemverilog'."
    )


def resolve_rtl_filename(filename: str, language: str) -> str:
    """Validate ``filename`` and ensure it matches ``language``."""
    cleaned = filename.strip()
    if not cleaned:
        raise InvalidSourceError("Filename must not be empty.")
    if "/" in cleaned or "\\" in cleaned:
        raise InvalidSourceError(
            "Filename must not contain path separators. "
            "Path traversal is not allowed."
        )
    if ".." in cleaned:
        raise InvalidSourceError("Filename must not contain '..'.")
    if cleaned.startswith(".") or not _FILENAME_PATTERN.fullmatch(cleaned):
        raise InvalidSourceError(
            f"Invalid RTL filename: {filename!r}. "
            "Use a simple basename such as 'counter.v'."
        )

    path = Path(cleaned)
    suffix = path.suffix.lower()
    expected = _LANGUAGE_EXTENSIONS[language]
    if suffix == "":
        return cleaned + expected
    if suffix not in _EXTENSION_LANGUAGES:
        raise InvalidSourceError(
            f"Unsupported RTL extension {suffix!r}. Use .v or .sv."
        )
    inferred = _EXTENSION_LANGUAGES[suffix]
    if inferred != language:
        raise InvalidSourceError(
            f"Filename extension {suffix} does not match language {language!r}."
        )
    return cleaned


def language_from_path(path: Path) -> str:
    """Infer language from a source file extension."""
    suffix = path.suffix.lower()
    if suffix not in _EXTENSION_LANGUAGES:
        raise InvalidSourceError(
            f"Unsupported source extension {suffix!r} for {path}. Use .v or .sv."
        )
    return _EXTENSION_LANGUAGES[suffix]


def parse_source_list(stdout: str) -> list[SourceInfo]:
    """Parse ``VIVADO_MCP_SOURCE_*`` markers from list_sources Tcl output."""
    sources: list[SourceInfo] = []
    current_path: str | None = None
    current_type = "unknown"
    current_library: str | None = None

    for match in _MARKER_PATTERN.finditer(stdout):
        key = match.group(1)
        value = match.group(2).strip()
        if key == "SOURCE_PATH":
            current_path = value
            current_type = "unknown"
            current_library = None
        elif key == "SOURCE_TYPE" and current_path is not None:
            current_type = map_vivado_file_type(value)
        elif key == "SOURCE_LIBRARY" and current_path is not None:
            current_library = value or None
        elif key == "SOURCE_END" and current_path is not None:
            file_type = current_type
            if file_type == "unknown":
                try:
                    file_type = language_from_path(Path(current_path))
                except InvalidSourceError:
                    file_type = "unknown"
            sources.append(
                SourceInfo(
                    path=current_path,
                    type=file_type,
                    library=current_library,
                )
            )
            current_path = None

    return sources


def map_vivado_file_type(file_type: str) -> str:
    """Map Vivado FILE_TYPE property to a normalized language label."""
    cleaned = file_type.strip().lower()
    return _VIVADO_FILE_TYPE_MAP.get(cleaned, cleaned or "unknown")


def _ensure_inside_directory(path: Path, directory: Path) -> None:
    """Reject resolved paths that escape ``directory``."""
    try:
        path.relative_to(directory)
    except ValueError as exc:
        raise InvalidSourceError(
            f"Refusing to write outside the project rtl directory: {path}"
        ) from exc


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


def _failure(exc: VivadoMCPError) -> SourceOperationResult:
    logger.info("Source operation failed: %s (%s)", exc.code, exc.message)
    error: dict[str, str] = {
        "type": type(exc).__name__,
        "code": exc.code,
        "message": exc.message,
    }
    if isinstance(exc, VivadoExecutionError):
        detail = _trim_output(exc.stdout, exc.stderr)
        if detail:
            error["vivado_output"] = detail
    return SourceOperationResult(success=False, error=error)
