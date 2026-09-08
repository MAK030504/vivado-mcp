"""Unit tests for Tcl helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from vivado_mcp.errors import InvalidPartError, InvalidProjectPathError
from vivado_mcp.tcl import (
    build_close_project_tcl,
    build_create_project_tcl,
    build_open_project_tcl,
    normalize_user_path,
    tcl_quote,
    validate_part,
    validate_project_name,
)


def test_validate_project_name_accepts_valid() -> None:
    assert validate_project_name("counter") == "counter"
    assert validate_project_name("Top_1") == "Top_1"


def test_validate_project_name_rejects_invalid() -> None:
    with pytest.raises(InvalidProjectPathError):
        validate_project_name("")
    with pytest.raises(InvalidProjectPathError):
        validate_project_name("my project")
    with pytest.raises(InvalidProjectPathError):
        validate_project_name("1abc")
    with pytest.raises(InvalidProjectPathError):
        validate_project_name("foo;bar")


def test_validate_part_accepts_common_parts() -> None:
    assert validate_part("xc7a35tcpg236-1") == "xc7a35tcpg236-1"
    assert validate_part("xc7a35tcpg236-1") == "xc7a35tcpg236-1"


def test_validate_part_rejects_invalid() -> None:
    with pytest.raises(InvalidPartError):
        validate_part("")
    with pytest.raises(InvalidPartError):
        validate_part("xc7 a35")
    with pytest.raises(InvalidPartError):
        validate_part("part}bad")


def test_normalize_user_path_expands_and_keeps_spaces(tmp_path: Path) -> None:
    spaced = tmp_path / "Vivado Projects" / "counter"
    result = normalize_user_path(str(spaced))
    assert result == spaced
    assert "Vivado Projects" in str(result)


def test_normalize_user_path_windows_style() -> None:
    result = normalize_user_path(r"C:\Users\User Name\Documents\Vivado Projects\counter")
    text = str(result)
    assert "counter" in text
    assert "User Name" in text


def test_normalize_user_path_linux_style() -> None:
    result = normalize_user_path("/home/user/fpga projects/counter")
    assert result.as_posix() == "/home/user/fpga projects/counter"


def test_normalize_user_path_rejects_empty_and_null() -> None:
    with pytest.raises(InvalidProjectPathError):
        normalize_user_path("  ")
    with pytest.raises(InvalidProjectPathError):
        normalize_user_path("abc\x00def")


def test_tcl_quote_wraps_and_rejects_braces() -> None:
    assert tcl_quote(r"C:\Users\User Name\proj") == r"{C:\Users\User Name\proj}"
    with pytest.raises(InvalidProjectPathError):
        tcl_quote("bad}value")


def test_build_create_project_tcl_quotes_spaces() -> None:
    parent = Path(r"C:\Users\User Name\Documents\Vivado Projects")
    script = build_create_project_tcl(
        name="counter",
        parent_dir=parent,
        part="xc7a35tcpg236-1",
    )
    assert "create_project {counter}" in script
    assert "User Name" in script
    assert "Vivado Projects" in script
    assert "\\" not in script.split("create_project", 1)[1].split("\n", 1)[0]
    assert "{xc7a35tcpg236-1}" in script
    assert "VIVADO_MCP_STATUS=OK" in script
    assert "close_project" in script
    assert "exit 0" in script


def test_build_open_and_close_tcl() -> None:
    xpr = Path("/home/user/fpga projects/counter/counter.xpr")
    open_script = build_open_project_tcl(xpr_path=xpr)
    close_script = build_close_project_tcl(xpr_path=xpr)
    assert "{/home/user/fpga projects/counter/counter.xpr}" in open_script
    assert "open_project" in open_script
    assert "close_project" in open_script
    assert "{/home/user/fpga projects/counter/counter.xpr}" in close_script
    assert "open_project" in close_script
    assert "VIVADO_MCP_CLOSED=1" in close_script
    # Stale lock cleanup / retry path for Windows reliability.
    assert ".lck" in open_script
    assert ".lck" in close_script
    assert "file delete -force" in close_script
