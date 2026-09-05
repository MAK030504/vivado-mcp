"""Vivado executable abstraction.

All Vivado process interaction lives here. MCP tool handlers must not launch
subprocesses directly; they call this layer instead.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from vivado_mcp.config import Config
from vivado_mcp.errors import (
    VivadoExecutionError,
    VivadoNotFoundError,
    VivadoVersionParseError,
)

logger = logging.getLogger(__name__)

# Vivado prints lines such as: "Vivado v2024.2 (64-bit)"
_VERSION_PATTERN = re.compile(
    r"Vivado\s+v?(?P<version>\d{4}\.\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Directory names under .../Vivado/<version>/
_VERSION_DIR_PATTERN = re.compile(r"^\d{4}\.\d+(?:\.\d+)?$")

_NOT_FOUND_HELP = (
    "Vivado was not found. Install AMD/Xilinx Vivado, ensure the vivado "
    "executable is on PATH, or set the VIVADO_PATH environment variable to "
    "the full path of the Vivado executable "
    "(for example /tools/Xilinx/Vivado/2024.2/bin/vivado on Linux, or "
    r"C:\Xilinx\Vivado\2024.2\bin\vivado.bat on Windows)."
)


@dataclass(frozen=True, slots=True)
class VivadoVersionInfo:
    """Structured Vivado installation / version information."""

    installed: bool
    version: str | None
    executable: str | None
    platform: str
    error: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, str | bool | None]:
        """Return a JSON-serializable dictionary for MCP clients."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Result of invoking the Vivado executable."""

    returncode: int
    stdout: str
    stderr: str
    args: tuple[str, ...]


class Vivado:
    """Locate, validate, and invoke the Vivado executable.

    This class is the only place that should spawn Vivado processes.
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        platform_name: str | None = None,
        path_env: Mapping[str, str] | None = None,
        which: Callable[[str], str | None] | None = None,
        runner: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or Config.from_env()
        self._platform = (platform_name or platform.system()).lower()
        self._path_env = dict(path_env) if path_env is not None else None
        self._which = which or shutil.which
        self._runner = runner or _default_runner

    @property
    def platform_name(self) -> str:
        """Normalized platform label: ``windows``, ``linux``, or ``darwin``."""
        if self._platform.startswith("win"):
            return "windows"
        if self._platform == "darwin":
            return "darwin"
        return "linux"

    def get_version(self) -> VivadoVersionInfo:
        """Resolve Vivado and return structured version information.

        Never raises for a missing installation: callers receive
        ``installed=False`` with a helpful message. Execution / parse
        failures after a candidate executable is found are reported the
        same way so MCP clients always get structured data.
        """
        try:
            executable = self.resolve_executable()
        except VivadoNotFoundError as exc:
            logger.info("Vivado not found: %s", exc.message)
            return VivadoVersionInfo(
                installed=False,
                version=None,
                executable=None,
                platform=self.platform_name,
                error=exc.code,
                message=exc.message,
            )

        try:
            result = self.run(["-version"], timeout=60.0)
        except VivadoExecutionError as exc:
            logger.warning("Vivado version command failed: %s", exc.message)
            return VivadoVersionInfo(
                installed=False,
                version=None,
                executable=str(executable),
                platform=self.platform_name,
                error=exc.code,
                message=exc.message,
            )

        combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
        try:
            version = parse_vivado_version(combined)
        except VivadoVersionParseError as exc:
            logger.warning("Could not parse Vivado version output")
            return VivadoVersionInfo(
                installed=False,
                version=None,
                executable=str(executable),
                platform=self.platform_name,
                error=exc.code,
                message=exc.message,
            )

        return VivadoVersionInfo(
            installed=True,
            version=version,
            executable=str(executable),
            platform=self.platform_name,
            error=None,
            message=None,
        )

    def resolve_executable(self) -> Path:
        """Locate and validate the Vivado executable.

        Raises:
            VivadoNotFoundError: If no valid executable can be found.
        """
        candidates: list[Path] = []

        if self.config.vivado_path is not None:
            candidates.append(self.config.vivado_path)
        else:
            candidates.extend(self._detect_candidates())

        seen: set[Path] = set()
        tried: list[str] = []
        for candidate in candidates:
            resolved = candidate.expanduser()
            key = resolved
            try:
                key = resolved.resolve(strict=False)
            except OSError:
                pass
            if key in seen:
                continue
            seen.add(key)
            tried.append(str(resolved))
            if self._is_valid_executable(resolved):
                logger.debug("Using Vivado executable: %s", resolved)
                return resolved

        details = ""
        if tried:
            details = " Candidates checked: " + ", ".join(tried) + "."
        raise VivadoNotFoundError(_NOT_FOUND_HELP + details)

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = 120.0,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run the Vivado executable with the given arguments.

        This method is intentionally not exposed as an MCP tool. Future MCP
        tools should call higher-level helpers that use controlled argument
        lists only.
        """
        executable = self.resolve_executable()
        command = [str(executable), *args]
        logger.debug("Executing Vivado command: %s", command)

        merged_env = os.environ.copy()
        if self._path_env is not None:
            merged_env.update(self._path_env)
        if env is not None:
            merged_env.update(env)

        try:
            completed = self._runner(
                command,
                timeout=timeout,
                cwd=str(cwd) if cwd is not None else None,
                env=merged_env,
            )
        except FileNotFoundError as exc:
            raise VivadoNotFoundError(
                f"Vivado executable could not be started: {executable}. {exc}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise VivadoExecutionError(
                f"Vivado timed out after {timeout} seconds.",
                returncode=None,
                stdout=_decode(exc.stdout),
                stderr=_decode(exc.stderr),
            ) from exc
        except OSError as exc:
            raise VivadoExecutionError(
                f"Failed to execute Vivado: {exc}",
                returncode=None,
            ) from exc

        result = CommandResult(
            returncode=int(completed.returncode),
            stdout=_decode(completed.stdout),
            stderr=_decode(completed.stderr),
            args=tuple(command),
        )
        if result.returncode != 0:
            raise VivadoExecutionError(
                f"Vivado exited with code {result.returncode}.",
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    def _detect_candidates(self) -> list[Path]:
        """Return candidate executable paths for the current platform."""
        candidates: list[Path] = []

        for name in self._executable_names():
            found = self._which(name)
            if found:
                candidates.append(Path(found))

        install_roots = self._default_install_roots()
        version_dirs: list[tuple[str, Path]] = []
        for root in install_roots:
            if not root.is_dir():
                continue
            try:
                children = list(root.iterdir())
            except OSError:
                continue
            for child in children:
                if child.is_dir() and _VERSION_DIR_PATTERN.match(child.name):
                    version_dirs.append((child.name, child))

        preferred = self.config.preferred_version
        if preferred:
            preferred_matches = [path for ver, path in version_dirs if ver == preferred]
            version_dirs = [
                (ver, path) for ver, path in version_dirs if ver != preferred
            ]
            # Prefer the configured version, then newest remaining installs.
            ordered = preferred_matches + [
                path for _, path in sorted(version_dirs, key=lambda item: item[0], reverse=True)
            ]
        else:
            ordered = [
                path for _, path in sorted(version_dirs, key=lambda item: item[0], reverse=True)
            ]

        for version_dir in ordered:
            for relative in self._executable_relative_paths():
                candidates.append(version_dir / relative)

        return candidates

    def _executable_names(self) -> tuple[str, ...]:
        if self.platform_name == "windows":
            return ("vivado.bat", "vivado.exe", "vivado")
        return ("vivado",)

    def _executable_relative_paths(self) -> tuple[Path, ...]:
        if self.platform_name == "windows":
            return (
                Path("bin") / "vivado.bat",
                Path("bin") / "vivado.exe",
                Path("bin") / "vivado",
            )
        return (Path("bin") / "vivado",)

    def _default_install_roots(self) -> list[Path]:
        """Common Vivado install roots (no hard-coded single path)."""
        home = Path.home()
        if self.platform_name == "windows":
            drives = ["C:", "D:"]
            vendors = ["Xilinx", "AMD", "AMD\\Xilinx"]
            roots: list[Path] = []
            for drive in drives:
                for vendor in vendors:
                    roots.append(Path(f"{drive}\\{vendor}\\Vivado"))
            roots.extend(
                [
                    home / "Xilinx" / "Vivado",
                    home / "AMD" / "Vivado",
                ]
            )
            return roots

        return [
            Path("/tools/Xilinx/Vivado"),
            Path("/opt/Xilinx/Vivado"),
            Path("/opt/AMD/Vivado"),
            Path("/opt/amd/Vivado"),
            Path("/usr/local/Xilinx/Vivado"),
            home / "Xilinx" / "Vivado",
            home / "AMD" / "Vivado",
            home / "tools" / "Xilinx" / "Vivado",
        ]

    def _is_valid_executable(self, path: Path) -> bool:
        if not path.exists() or not path.is_file():
            return False
        if self.platform_name == "windows":
            return path.suffix.lower() in {".bat", ".cmd", ".exe"} or os.access(
                path, os.X_OK
            )
        return os.access(path, os.X_OK)


def parse_vivado_version(output: str) -> str:
    """Extract a Vivado version string from ``vivado -version`` output."""
    if not output or not output.strip():
        raise VivadoVersionParseError(
            "Vivado produced empty version output.",
            raw_output=output,
        )

    match = _VERSION_PATTERN.search(output)
    if not match:
        raise VivadoVersionParseError(
            "Could not parse Vivado version from command output. "
            "Ensure the configured executable is a real Vivado binary.",
            raw_output=output,
        )
    return match.group("version")


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode(sys.stdout.encoding or "utf-8", errors="replace")


def _default_runner(
    command: Sequence[str],
    *,
    timeout: float | None,
    cwd: str | None,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        list(command),
        capture_output=True,
        timeout=timeout,
        cwd=cwd,
        env=dict(env),
        check=False,
    )
