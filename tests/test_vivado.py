"""Unit tests for the Vivado abstraction layer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from vivado_mcp.config import Config
from vivado_mcp.errors import VivadoNotFoundError, VivadoVersionParseError
from vivado_mcp.vivado import Vivado, parse_vivado_version


class FakeCompletedProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_explicit_vivado_path_is_used(tmp_path: Path) -> None:
    executable = _make_executable(tmp_path / "vivado")
    output = b"Vivado v2024.2 (64-bit)\n"

    def runner(command: list[str], **_: Any) -> FakeCompletedProcess:
        assert command[0] == str(executable)
        assert command[1:] == ["-version"]
        return FakeCompletedProcess(stdout=output)

    vivado = Vivado(
        Config(vivado_path=executable),
        platform_name="Linux",
        runner=runner,
    )
    info = vivado.get_version()

    assert info.installed is True
    assert info.version == "2024.2"
    assert info.executable == str(executable)
    assert info.platform == "linux"
    assert info.error is None


def test_missing_vivado_returns_structured_error() -> None:
    vivado = Vivado(
        Config(),
        platform_name="Linux",
        which=lambda _name: None,
        runner=lambda *_args, **_kwargs: FakeCompletedProcess(),
    )
    # Force empty detection roots by using a home-less custom instance path set.
    vivado._default_install_roots = lambda: []  # type: ignore[method-assign]

    info = vivado.get_version()

    assert info.installed is False
    assert info.version is None
    assert info.executable is None
    assert info.platform == "linux"
    assert info.error == "vivado_not_found"
    assert info.message is not None
    assert "VIVADO_PATH" in info.message


def test_explicit_missing_path_fails_cleanly(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist" / "vivado"
    vivado = Vivado(Config(vivado_path=missing), platform_name="Linux")
    info = vivado.get_version()

    assert info.installed is False
    assert info.error == "vivado_not_found"
    assert str(missing) in (info.message or "")


def test_start_menu_folder_resolves_via_shortcut_target(
    tmp_path: Path, monkeypatch
) -> None:
    start_menu = tmp_path / "Start Menu" / "Programs" / "Xilinx Design Tools" / "Vivado 2018.2"
    start_menu.mkdir(parents=True)
    shortcut = start_menu / "Vivado 2018.2.lnk"
    shortcut.write_bytes(b"placeholder")

    real = _make_executable(tmp_path / "custom" / "vivado.bat")

    monkeypatch.setattr(
        "vivado_mcp.vivado.read_shortcut_target",
        lambda path: real if path == shortcut else None,
    )

    vivado = Vivado(
        Config(vivado_path=start_menu),
        platform_name="Windows",
        which=lambda _name: None,
    )
    vivado._default_install_roots = lambda: []  # type: ignore[method-assign]

    assert vivado.resolve_executable() == real


def test_vvgl_helper_path_resolves_to_vivado_bat(tmp_path: Path) -> None:
    """Custom installs may expose vvgl.exe; resolve to bin/vivado.bat."""
    version_dir = tmp_path / "Softwares" / "Vivado" / "2018.2"
    executable = _make_executable(version_dir / "bin" / "vivado.bat")
    helper = version_dir / "bin" / "unwrapped" / "win64.o" / "vvgl.exe"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("helper", encoding="utf-8")

    vivado = Vivado(
        Config(vivado_path=helper),
        platform_name="Windows",
        which=lambda _name: None,
    )
    vivado._default_install_roots = lambda: []  # type: ignore[method-assign]

    assert vivado.resolve_executable() == executable


def test_softwares_install_root_is_searched(tmp_path: Path) -> None:
    root = tmp_path / "Softwares" / "Vivado"
    executable = _make_executable(root / "2018.2" / "bin" / "vivado.bat")

    vivado = Vivado(
        Config(preferred_version="2018.2"),
        platform_name="Windows",
        which=lambda _name: None,
    )
    vivado._default_install_roots = lambda: [root]  # type: ignore[method-assign]

    assert vivado.resolve_executable() == executable

    """Accept the Windows Start Menu folder and map it to vivado.bat."""
    start_menu = (
        tmp_path
        / "Users"
        / "HP"
        / "AppData"
        / "Roaming"
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Xilinx Design Tools"
        / "Vivado 2018.2"
    )
    start_menu.mkdir(parents=True)

    install_root = tmp_path / "Xilinx" / "Vivado"
    executable = _make_executable(install_root / "2018.2" / "bin" / "vivado.bat")

    vivado = Vivado(
        Config(vivado_path=start_menu),
        platform_name="Windows",
        which=lambda _name: None,
    )
    vivado._default_install_roots = lambda: [install_root]  # type: ignore[method-assign]

    assert vivado.resolve_executable() == executable


def test_start_menu_folder_unresolved_gives_clear_error(tmp_path: Path) -> None:
    start_menu = tmp_path / "Start Menu" / "Programs" / "Xilinx Design Tools" / "Vivado 2018.2"
    start_menu.mkdir(parents=True)

    vivado = Vivado(
        Config(vivado_path=start_menu),
        platform_name="Windows",
        which=lambda _name: None,
    )
    vivado._default_install_roots = lambda: []  # type: ignore[method-assign]
    info = vivado.get_version()

    assert info.installed is False
    assert info.error == "vivado_not_found"
    assert "Start Menu" in (info.message or "")
    assert "vivado.bat" in (info.message or "")
    assert "2018.2" in (info.message or "")


def test_windows_shortcut_path_is_rejected(tmp_path: Path) -> None:
    shortcut = tmp_path / "Vivado 2018.2.lnk"
    shortcut.write_bytes(b"shortcut")

    info = Vivado(
        Config(vivado_path=shortcut),
        platform_name="Windows",
    ).get_version()

    assert info.installed is False
    assert info.error == "vivado_not_found"
    assert ".lnk" in (info.message or "")
    assert "vivado.bat" in (info.message or "")


def test_platform_detection_windows() -> None:
    vivado = Vivado(Config(), platform_name="Windows")
    assert vivado.platform_name == "windows"
    assert vivado._executable_names()[0] == "vivado.bat"


def test_platform_detection_linux() -> None:
    vivado = Vivado(Config(), platform_name="Linux")
    assert vivado.platform_name == "linux"
    assert vivado._executable_names() == ("vivado",)


def test_platform_detection_darwin() -> None:
    vivado = Vivado(Config(), platform_name="Darwin")
    assert vivado.platform_name == "darwin"


def test_parse_vivado_version_typical_output() -> None:
    raw = """
****** Vivado v2024.2 (64-bit)
  **** SW Build 5239630 on Fri Nov 08 14:30:00 MST 2024
  **** IP Build 5239520 on Fri Nov 08 14:00:00 MST 2024
"""
    assert parse_vivado_version(raw) == "2024.2"


def test_parse_vivado_version_2018_2_banner() -> None:
    raw = """
****** Vivado v2018.2 (64-bit)
  **** SW Build 2258646 on Thu Jun 14 20:02:38 MDT 2018
  **** IP Build 2256618 on Thu Jun 14 22:10:49 MDT 2018
    ** Copyright 1986-2018 Xilinx, Inc. All Rights Reserved.
"""
    assert parse_vivado_version(raw) == "2018.2"


def test_parse_vivado_version_without_v_prefix() -> None:
    assert parse_vivado_version("Vivado 2023.1 (64-bit)") == "2023.1"


def test_parse_vivado_version_empty_raises() -> None:
    with pytest.raises(VivadoVersionParseError) as exc_info:
        parse_vivado_version("   ")
    assert exc_info.value.code == "vivado_version_parse_error"


def test_parse_vivado_version_malformed_raises() -> None:
    with pytest.raises(VivadoVersionParseError):
        parse_vivado_version("not a vivado banner at all")


def test_malformed_vivado_output_returns_structured_error(tmp_path: Path) -> None:
    executable = _make_executable(tmp_path / "vivado")

    def runner(_command: list[str], **_: Any) -> FakeCompletedProcess:
        return FakeCompletedProcess(stdout=b"garbage output without version")

    vivado = Vivado(
        Config(vivado_path=executable),
        platform_name="Linux",
        runner=runner,
    )
    info = vivado.get_version()

    assert info.installed is False
    assert info.executable == str(executable)
    assert info.error == "vivado_version_parse_error"
    assert info.message is not None


def test_failed_vivado_exit_returns_structured_error(tmp_path: Path) -> None:
    executable = _make_executable(tmp_path / "vivado")

    def runner(_command: list[str], **_: Any) -> FakeCompletedProcess:
        return FakeCompletedProcess(
            returncode=1,
            stdout=b"",
            stderr=b"license check failed",
        )

    vivado = Vivado(
        Config(vivado_path=executable),
        platform_name="Linux",
        runner=runner,
    )
    info = vivado.get_version()

    assert info.installed is False
    assert info.error == "vivado_execution_error"
    assert "exited with code 1" in (info.message or "")


def test_resolve_executable_from_path_which(tmp_path: Path) -> None:
    executable = _make_executable(tmp_path / "vivado")

    vivado = Vivado(
        Config(),
        platform_name="Linux",
        which=lambda name: str(executable) if name == "vivado" else None,
    )
    vivado._default_install_roots = lambda: []  # type: ignore[method-assign]

    assert vivado.resolve_executable() == executable


def test_preferred_version_selected_from_install_tree(tmp_path: Path) -> None:
    root = tmp_path / "Xilinx" / "Vivado"
    older = _make_executable(root / "2023.1" / "bin" / "vivado")
    preferred = _make_executable(root / "2024.1" / "bin" / "vivado")
    newer = _make_executable(root / "2024.2" / "bin" / "vivado")
    del older, newer  # present on disk; preferred must win

    vivado = Vivado(
        Config(preferred_version="2024.1"),
        platform_name="Linux",
        which=lambda _name: None,
    )
    vivado._default_install_roots = lambda: [root]  # type: ignore[method-assign]

    assert vivado.resolve_executable() == preferred


def test_newest_version_selected_without_preference(tmp_path: Path) -> None:
    root = tmp_path / "Xilinx" / "Vivado"
    _make_executable(root / "2023.1" / "bin" / "vivado")
    newest = _make_executable(root / "2024.2" / "bin" / "vivado")

    vivado = Vivado(
        Config(),
        platform_name="Linux",
        which=lambda _name: None,
    )
    vivado._default_install_roots = lambda: [root]  # type: ignore[method-assign]

    assert vivado.resolve_executable() == newest


def test_windows_bat_candidate_is_accepted(tmp_path: Path) -> None:
    bat = tmp_path / "vivado.bat"
    bat.write_text("@echo off\n", encoding="utf-8")

    vivado = Vivado(
        Config(vivado_path=bat),
        platform_name="Windows",
    )
    assert vivado.resolve_executable() == bat


def test_version_info_to_dict_shape(tmp_path: Path) -> None:
    executable = _make_executable(tmp_path / "vivado")

    def runner(_command: list[str], **_: Any) -> FakeCompletedProcess:
        return FakeCompletedProcess(stdout=b"Vivado v2022.2 (64-bit)\n")

    info = Vivado(
        Config(vivado_path=executable),
        platform_name="Linux",
        runner=runner,
    ).get_version()

    payload = info.to_dict()
    assert payload == {
        "installed": True,
        "version": "2022.2",
        "executable": str(executable),
        "platform": "linux",
        "error": None,
        "message": None,
    }


@pytest.mark.integration
def test_integration_real_vivado_if_available() -> None:
    """Optional live check; skipped when Vivado is not installed."""
    vivado = Vivado(Config.from_env())
    try:
        executable = vivado.resolve_executable()
    except VivadoNotFoundError:
        pytest.skip("Vivado is not installed on this machine")

    info = vivado.get_version()
    assert info.installed is True
    assert info.version is not None
    assert info.executable == str(executable)
    assert info.platform in {"linux", "windows", "darwin"}


def test_timeout_is_reported(tmp_path: Path) -> None:
    executable = _make_executable(tmp_path / "vivado")

    def runner(_command: list[str], **_: Any) -> FakeCompletedProcess:
        raise subprocess.TimeoutExpired(cmd=["vivado", "-version"], timeout=1)

    info = Vivado(
        Config(vivado_path=executable),
        platform_name="Linux",
        runner=runner,
    ).get_version()

    assert info.installed is False
    assert info.error == "vivado_execution_error"
    assert "timed out" in (info.message or "").lower()


def test_non_executable_file_rejected(tmp_path: Path) -> None:
    path = tmp_path / "vivado"
    path.write_text("not executable", encoding="utf-8")
    os.chmod(path, 0o644)

    vivado = Vivado(Config(vivado_path=path), platform_name="Linux")
    with pytest.raises(VivadoNotFoundError):
        vivado.resolve_executable()
