"""Domain-specific errors for Vivado MCP."""

from __future__ import annotations


class VivadoMCPError(Exception):
    """Base error for Vivado MCP."""

    def __init__(self, message: str, *, code: str = "vivado_mcp_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class VivadoNotFoundError(VivadoMCPError):
    """Raised when the Vivado executable cannot be located or validated."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="vivado_not_found")


class VivadoExecutionError(VivadoMCPError):
    """Raised when a Vivado process fails or returns unusable output."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message, code="vivado_execution_error")
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class VivadoVersionParseError(VivadoMCPError):
    """Raised when Vivado version output cannot be parsed."""

    def __init__(self, message: str, *, raw_output: str = "") -> None:
        super().__init__(message, code="vivado_version_parse_error")
        self.raw_output = raw_output


class ConfigError(VivadoMCPError):
    """Raised when configuration is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="config_error")


class InvalidProjectPathError(VivadoMCPError):
    """Raised when a project path or name is invalid / unsafe."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_project_path")


class ProjectAlreadyExistsError(VivadoMCPError):
    """Raised when create_project would overwrite an existing project."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="project_already_exists")


class ProjectNotFoundError(VivadoMCPError):
    """Raised when an expected Vivado project (.xpr) cannot be found."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="project_not_found")


class InvalidPartError(VivadoMCPError):
    """Raised when a Vivado FPGA part string is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_part")


class InvalidSourceError(VivadoMCPError):
    """Raised when an RTL filename, language, or source path is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_source")


class SourceAlreadyExistsError(VivadoMCPError):
    """Raised when creating an RTL file that already exists on disk."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="source_already_exists")


class SourceNotFoundError(VivadoMCPError):
    """Raised when a source file is missing or not in the project."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="source_not_found")


class InvalidSimulationTimeError(VivadoMCPError):
    """Raised when a simulation runtime string is invalid or unsafe."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_simulation_time")


class InvalidTopModuleError(VivadoMCPError):
    """Raised when a simulation top module name is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_top_module")


class NoSimulationSourcesError(VivadoMCPError):
    """Raised when a project has no simulation sources in ``sim_1``."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="no_simulation_sources")


class SimulationError(VivadoMCPError):
    """Raised when Vivado simulation fails (compile/elaborate/runtime/etc.)."""

    def __init__(
        self,
        message: str,
        *,
        status: str = "failed",
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message, code="simulation_error")
        self.status = status
        self.stdout = stdout
        self.stderr = stderr


class SynthesisError(VivadoMCPError):
    """Raised when Vivado synthesis fails or prerequisites are missing."""

    def __init__(
        self,
        message: str,
        *,
        status: str = "failed",
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message, code="synthesis_error")
        self.status = status
        self.stdout = stdout
        self.stderr = stderr


class SynthesisNotRunError(VivadoMCPError):
    """Raised when a report is requested before synthesis has completed."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="synthesis_not_run")


class ReportNotAvailableError(VivadoMCPError):
    """Raised when a Vivado report cannot be produced or parsed."""

    def __init__(self, message: str, *, status: str = "not_available") -> None:
        super().__init__(message, code="report_not_available")
        self.status = status
