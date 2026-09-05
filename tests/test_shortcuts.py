"""Tests for Windows .lnk target parsing."""

from __future__ import annotations

import struct
from pathlib import Path

from vivado_mcp.shortcuts import read_shortcut_target


def _build_local_lnk(target: str) -> bytes:
    """Build a minimal local-file .lnk with ASCII LocalBasePath."""
    target_bytes = target.encode("ascii") + b"\x00"
    # LinkInfo layout:
    # 0 size, 4 header size (0x1C), 8 flags (volume+local), 12 vol offset,
    # 16 local base path offset, 20 common network relative, 24 common path suffix
    header_size = 0x1C
    local_base_path_offset = header_size
    link_info = struct.pack(
        "<IIIIIII",
        header_size + len(target_bytes),  # LinkInfoSize (patched below)
        header_size,
        0x01,  # VolumeIDAndLocalBasePath
        0,  # VolumeIDOffset unused
        local_base_path_offset,
        0,
        0,
    ) + target_bytes
    link_info = struct.pack("<I", len(link_info)) + link_info[4:]

    # Shell Link Header (0x4C bytes), LinkFlags = HasLinkInfo only (0x02)
    header = bytearray(0x4C)
    struct.pack_into("<I", header, 0, 0x4C)
    header[4:20] = bytes.fromhex("0114020000000000C000000000000046")
    struct.pack_into("<I", header, 0x14, 0x02)
    return bytes(header) + link_info


def test_read_shortcut_target_local_path(tmp_path: Path) -> None:
    shortcut = tmp_path / "Vivado 2018.2.lnk"
    target = r"C:\Xilinx\Vivado\2018.2\bin\vivado.bat"
    shortcut.write_bytes(_build_local_lnk(target))

    assert read_shortcut_target(shortcut) == Path(target)


def test_read_shortcut_target_rejects_garbage(tmp_path: Path) -> None:
    shortcut = tmp_path / "bad.lnk"
    shortcut.write_bytes(b"not a shortcut")
    assert read_shortcut_target(shortcut) is None
