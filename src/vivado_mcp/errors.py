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
