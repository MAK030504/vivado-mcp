"""Minimal Windows ``.lnk`` target extraction (no extra dependencies)."""

from __future__ import annotations

import struct
from pathlib import Path


def read_shortcut_target(path: Path) -> Path | None:
    """Return the target path stored in a Windows shortcut, if readable.

    Supports common local-file shortcuts created by the Vivado installer.
    Returns ``None`` when the file is not a parseable ``.lnk`` or the target
    path cannot be recovered.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None

    if len(data) < 0x4C:
        return None
    if data[0:4] != b"L\x00\x00\x00":
        return None

    flags = struct.unpack_from("<I", data, 0x14)[0]
    offset = 0x4C

    # HasLinkTargetIDList
    if flags & 0x01:
        if offset + 2 > len(data):
            return None
        id_list_size = struct.unpack_from("<H", data, offset)[0]
        offset += 2 + id_list_size

    # HasLinkInfo
    if not (flags & 0x02):
        return None
    if offset + 0x1C > len(data):
        return None

    link_info_size = struct.unpack_from("<I", data, offset)[0]
    link_info_header_size = struct.unpack_from("<I", data, offset + 4)[0]
    link_info_flags = struct.unpack_from("<I", data, offset + 8)[0]
    if link_info_size < 0x1C or offset + link_info_size > len(data):
        return None

    # VolumeIDAndLocalBasePath
    if not (link_info_flags & 0x01):
        return None

    local_base_path_offset = struct.unpack_from("<I", data, offset + 16)[0]
    target: str | None = None

    # Prefer Unicode local path when present (header size >= 0x24).
    if link_info_header_size >= 0x24:
        unicode_offset = struct.unpack_from("<I", data, offset + 28)[0]
        if unicode_offset and offset + unicode_offset < offset + link_info_size:
            target = _decode_utf16z(data, offset + unicode_offset)

    if not target:
        abs_offset = offset + local_base_path_offset
        if abs_offset >= offset + link_info_size:
            return None
        target = _decode_asciiz(data, abs_offset)

    if not target:
        return None
    return Path(target)


def _decode_asciiz(data: bytes, start: int) -> str | None:
    end = data.find(b"\x00", start)
    if end < 0:
        end = len(data)
    raw = data[start:end]
    for encoding in ("mbcs", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except LookupError:
            continue
        except UnicodeError:
            continue
    else:
        text = raw.decode("latin-1", errors="replace")
    return text or None


def _decode_utf16z(data: bytes, start: int) -> str | None:
    chars: list[str] = []
    index = start
    while index + 1 < len(data):
        value = struct.unpack_from("<H", data, index)[0]
        index += 2
        if value == 0:
            break
        chars.append(chr(value))
    text = "".join(chars)
    return text or None
