"""Unit tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

from vivado_mcp.config import (
    ENV_VIVADO_PATH,
    ENV_VIVADO_VERSION,
    ENV_VIVADO_WORKSPACE,
    Config,
)


def test_from_env_reads_vivado_path() -> None:
    config = Config.from_env(
        environ={ENV_VIVADO_PATH: "/opt/Xilinx/Vivado/2024.2/bin/vivado"},
    )
    assert config.vivado_path == Path("/opt/Xilinx/Vivado/2024.2/bin/vivado")
    assert config.preferred_version is None
    assert config.workspace is None


def test_from_env_reads_optional_fields() -> None:
    config = Config.from_env(
        environ={
            ENV_VIVADO_PATH: "C:/Xilinx/Vivado/2023.2/bin/vivado.bat",
            ENV_VIVADO_VERSION: "2023.2",
            ENV_VIVADO_WORKSPACE: "/home/user/fpga-projects",
        },
    )
    assert config.vivado_path == Path("C:/Xilinx/Vivado/2023.2/bin/vivado.bat")
    assert config.preferred_version == "2023.2"
    assert config.workspace == Path("/home/user/fpga-projects")


def test_explicit_values_override_environment() -> None:
    config = Config.from_env(
        environ={
            ENV_VIVADO_PATH: "/from/env/vivado",
            ENV_VIVADO_VERSION: "2022.1",
            ENV_VIVADO_WORKSPACE: "/from/env/ws",
        },
        vivado_path="/explicit/vivado",
        preferred_version="2024.2",
        workspace="/explicit/ws",
    )
    assert config.vivado_path == Path("/explicit/vivado")
    assert config.preferred_version == "2024.2"
    assert config.workspace == Path("/explicit/ws")


def test_blank_environment_values_are_treated_as_unset() -> None:
    config = Config.from_env(
        environ={
            ENV_VIVADO_PATH: "   ",
            ENV_VIVADO_VERSION: "",
            ENV_VIVADO_WORKSPACE: "\t",
        },
    )
    assert config.vivado_path is None
    assert config.preferred_version is None
    assert config.workspace is None


def test_expanduser_on_paths(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("HOME", "/home/tester")
    config = Config.from_env(environ={ENV_VIVADO_PATH: "~/tools/vivado"})
    assert config.vivado_path == Path("/home/tester/tools/vivado")
