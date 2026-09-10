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
import tempfile
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
from vivado_mcp.shortcuts import read_shortcut_target


logger = logging.getLogger(__name__)

# Vivado prints lines such as: "Vivado v2024.2 (64-bit)"
_VERSION_PATTERN = re.compile(
    r"Vivado\s+v?(?P<version>\d{4}\.\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Directory names under .../Vivado/<version>/
_VERSION_DIR_PATTERN = re.compile(r"^\d{4}\.\d+(?:\.\d+)?$")

# Start Menu / shortcut folders are often named "Vivado 2018.2"
_START_MENU_VERSION_PATTERN = re.compile(
    r"Vivado\s+(?P<version>\d{4}\.\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

_NOT_FOUND_HELP = (
    "Vivado was not found. Install AMD/Xilinx Vivado, ensure the vivado "
    "executable is on PATH, or set the VIVADO_PATH environment variable to "
    "the full path of the Vivado executable "
    "(for example /tools/Xilinx/Vivado/2018.2/bin/vivado on Linux, or "
    r"C:\Xilinx\Vivado\2018.2\bin\vivado.bat on Windows). "
    "A Windows Start Menu folder such as "
    r"'...\Xilinx Design Tools\Vivado 2018.2' is also accepted; Vivado MCP "
    "will try to resolve it to vivado.bat under a normal Xilinx install root."
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
            configured = self.config.vivado_path.expanduser()
            if configured.suffix.lower() == ".lnk":
                target = read_shortcut_target(configured)
                if target is not None:
                    candidates.extend(self._candidates_from_shortcut_target(target))
                else:
                    raise VivadoNotFoundError(self._shortcut_path_error(configured))
            else:
                expanded = self._expand_configured_path(configured)
                if expanded:
                    candidates.extend(expanded)
                else:
                    candidates.append(configured)
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
        configured = self.config.vivado_path
        if configured is not None and self._looks_like_start_menu_path(
            configured.expanduser()
        ):
            raise VivadoNotFoundError(
                self._unresolved_start_menu_error(configured.expanduser()) + details
            )
        raise VivadoNotFoundError(_NOT_FOUND_HELP + details)

    def _expand_configured_path(self, path: Path) -> list[Path]:
        """Expand Start Menu / version folders into executable candidates.

        Users often paste the Windows Start Menu folder, for example::

            C:\\Users\\...\\Start Menu\\Programs\\Xilinx Design Tools\\Vivado 2018.2

        That folder is not the Vivado binary. When we can infer the version
        (from the folder name or ``VIVADO_VERSION``), search normal install
        roots for ``vivado.bat`` / ``vivado``.
        """
        results: list[Path] = []

        # Already looks like a launcher path.
        lowered = path.name.lower()
        if lowered in {"vivado", "vivado.bat", "vivado.exe", "vivado.cmd"}:
            return [path]

        # Paths deep inside an install (e.g. ...\bin\unwrapped\win64.o\vvgl.exe)
        # should resolve to that install's bin\vivado.bat.
        results.extend(self._candidates_from_install_tree(path))

        version = self._version_hint_from_path(path)

        if path.exists() and path.is_dir():
            for name in self._executable_names():
                results.append(path / name)
            for relative in self._executable_relative_paths():
                results.append(path / relative)
            # Resolve Start Menu .lnk files to their Target paths.
            try:
                children = list(path.iterdir())
            except OSError:
                children = []
            for child in children:
                if child.suffix.lower() != ".lnk":
                    continue
                target = read_shortcut_target(child)
                if target is not None:
                    results.extend(self._candidates_from_shortcut_target(target))

        if version:
            for root in self._default_install_roots():
                version_dir = root / version
                for relative in self._executable_relative_paths():
                    results.append(version_dir / relative)

        return results

    def _candidates_from_shortcut_target(self, target: Path) -> list[Path]:
        """Build executable candidates from a shortcut Target path."""
        results: list[Path] = []
        lowered = target.name.lower()
        if lowered in {"vivado", "vivado.bat", "vivado.exe", "vivado.cmd"}:
            return [target]

        # Helper binaries like vvgl.exe live under the install tree; map them
        # back to bin/vivado.bat.
        results.extend(self._candidates_from_install_tree(target))

        # Target sometimes points at a helper script or install folder.
        if target.exists() and target.is_dir():
            for relative in self._executable_relative_paths():
                results.append(target / relative)
            for name in self._executable_names():
                results.append(target / name)
        # If Target is under .../Vivado/<version>/..., also try known roots.
        version = self._version_hint_from_path(target)
        if version:
            for root in self._default_install_roots():
                version_dir = root / version
                for relative in self._executable_relative_paths():
                    results.append(version_dir / relative)
        return results

    def _candidates_from_install_tree(self, path: Path) -> list[Path]:
        """If ``path`` is inside a Vivado version directory, return its launchers.

        Handles custom layouts such as::

            D:\\Softwares\\Vivado\\2018.2\\bin\\unwrapped\\win64.o\\vvgl.exe
        """
        version_dir = self._find_vivado_version_dir(path)
        if version_dir is None:
            return []
        return [version_dir / relative for relative in self._executable_relative_paths()]

    def _find_vivado_version_dir(self, path: Path) -> Path | None:
        """Walk parents to find ``.../Vivado/<version>``."""
        chain = [path, *path.parents]
        for candidate in chain:
            if not _VERSION_DIR_PATTERN.match(candidate.name):
                continue
            if candidate.parent.name.lower() == "vivado":
                return candidate
            # Accept a bare version directory that already contains the launcher.
            for relative in self._executable_relative_paths():
                if (candidate / relative).exists():
                    return candidate
        return None

    def _version_hint_from_path(self, path: Path) -> str | None:
        match = _START_MENU_VERSION_PATTERN.search(path.name)
        if match:
            return match.group("version")
        for part in path.parts:
            if _VERSION_DIR_PATTERN.match(part):
                return part
        if self._looks_like_start_menu_path(path) and self.config.preferred_version:
            return self.config.preferred_version
        return None

    def _looks_like_start_menu_path(self, path: Path) -> bool:
        text = str(path).replace("/", "\\").lower()
        if "start menu" in text:
            return True
        if "xilinx design tools" in text:
            return True
        return _START_MENU_VERSION_PATTERN.search(path.name) is not None

    def _shortcut_path_error(self, path: Path) -> str:
        return (
            f"VIVADO_PATH points to a Windows shortcut (.lnk): {path}, "
            "and its Target could not be read. "
            "In PowerShell run:\n"
            r'  $s = (New-Object -ComObject WScript.Shell).CreateShortcut("'
            + str(path).replace('"', "")
            + r'"); $s.TargetPath'
            "\nThen set VIVADO_PATH to that Target (usually "
            r"C:\Xilinx\Vivado\2018.2\bin\vivado.bat)."
        )

    def _unresolved_start_menu_error(self, path: Path) -> str:
        version = self._version_hint_from_path(path) or "2018.2"
        return (
            f"VIVADO_PATH looks like a Windows Start Menu Vivado folder: {path}. "
            "That folder contains shortcuts, not the Vivado executable, and no "
            "matching install was found automatically. "
            "In PowerShell, discover the real launcher with:\n"
            f'  Get-ChildItem "{path}" -Filter *.lnk | '
            "ForEach-Object { "
            "(New-Object -ComObject WScript.Shell).CreateShortcut($_.FullName).TargetPath "
            "}\n"
            f"Then set VIVADO_PATH to that path (often "
            f"C:\\Xilinx\\Vivado\\{version}\\bin\\vivado.bat)."
        )


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

    def run_tcl(
        self,
        script: str,
        *,
        timeout: float | None = 300.0,
        cwd: Path | None = None,
    ) -> CommandResult:
        """Run a Tcl script in Vivado batch mode (non-GUI).

        The script is written to a temporary file and passed to Vivado via
        ``-mode batch -source``. Callers must supply fully constructed,
        validated Tcl — never raw user shell input.
        """
        work_dir = cwd
        with tempfile.TemporaryDirectory(prefix="vivado-mcp-") as tmp:
            tmp_path = Path(tmp)
            script_path = tmp_path / "vivado_mcp.tcl"
            script_path.write_text(script, encoding="utf-8", newline="\n")
            # Keep journals/logs out of the user's project tree.
            log_path = tmp_path / "vivado_mcp.log"
            journal_path = tmp_path / "vivado_mcp.jou"
            args = [
                "-mode",
                "batch",
                "-notrace",
                "-log",
                str(log_path),
                "-journal",
                str(journal_path),
                "-source",
                str(script_path),
            ]
            return self.run(args, timeout=timeout, cwd=work_dir)

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
                    Path("C:\\Program Files\\Xilinx\\Vivado"),
                    Path("C:\\Program Files (x86)\\Xilinx\\Vivado"),
                    Path("D:\\Program Files\\Xilinx\\Vivado"),
                    Path("C:\\Softwares\\Vivado"),
                    Path("D:\\Softwares\\Vivado"),
                    Path("E:\\Softwares\\Vivado"),
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
        name = path.name.lower()
        # Reject known GUI helper binaries; the CLI entrypoint is vivado(.bat).
        if name in {"vvgl.exe", "loader.bat", "xilinx.bat"}:
            return False
        if not name.startswith("vivado"):
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
