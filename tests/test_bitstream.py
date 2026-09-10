"""Unit tests for bitstream management (no real Vivado required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vivado_mcp.bitstream import (
    STATUS_AVAILABLE,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_NOT_AVAILABLE,
    STATUS_NOT_STARTED,
    STATUS_TIMEOUT,
    BitstreamManager,
    _validate_bitstream_path,
)
from vivado_mcp.config import Config
from vivado_mcp.errors import VivadoExecutionError
from vivado_mcp.reports import VivadoReportParser, classify_bitstream_run_status
from vivado_mcp.tcl import build_generate_bitstream_tcl
from vivado_mcp.vivado import CommandResult, Vivado, VivadoVersionInfo


def _make_project(tmp_path: Path, name: str = "demo") -> Path:
    xpr = tmp_path / f"{name}.xpr"
    xpr.write_text(f"# fake {name}\n", encoding="utf-8")
    return xpr


def _impl_bit_path(project_dir: Path, top: str = "counter") -> Path:
    runs = project_dir / f"{project_dir.name}.runs" / "impl_1"
    runs.mkdir(parents=True, exist_ok=True)
    bit = runs / f"{top}.bit"
    bit.write_bytes(b"BITSTREAM_FAKE_DATA_123456")
    return bit


class FakeVivado(Vivado):
    def __init__(
        self,
        *,
        mode: str = "success",
        stdout: str = "",
        stderr: str = "",
        bit_path: Path | None = None,
        project_dir: Path | None = None,
    ) -> None:
        super().__init__(Config(), platform_name="Linux")
        self.mode = mode
        self.stdout = stdout
        self.stderr = stderr
        self.bit_path = bit_path
        self.project_dir = project_dir
        self.scripts: list[str] = []

    def get_version(self) -> VivadoVersionInfo:
        return VivadoVersionInfo(
            installed=True,
            version="2018.2",
            executable="/fake/vivado",
            platform="linux",
        )

    def run_tcl(
        self,
        script: str,
        *,
        timeout: float | None = 300.0,
        cwd: Path | None = None,
    ) -> CommandResult:
        self.scripts.append(script)

        if "launch_runs impl_1 -to_step write_bitstream" in script:
            return self._handle_generate()

        # Status / path query scripts
        if "VIVADO_MCP_BITSTREAM_STATUS" in script or "write_bitstream" not in script:
            return self._handle_status()

        return CommandResult(
            returncode=0,
            stdout=self.stdout or "VIVADO_MCP_STATUS=OK\n",
            stderr="",
            args=("vivado",),
        )

    def _handle_generate(self) -> CommandResult:
        if self.mode == "blocked":
            return CommandResult(
                returncode=0,
                stdout=(
                    "VIVADO_MCP_STATUS=ERROR\n"
                    "VIVADO_MCP_BITSTREAM_STATUS=blocked\n"
                    "VIVADO_MCP_BITSTREAM_ERROR="
                    "Implementation must complete before bitstream generation\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=place_design Running\n"
                ),
                stderr="",
                args=("vivado",),
            )
        if self.mode == "missing_impl":
            return CommandResult(
                returncode=0,
                stdout=(
                    "VIVADO_MCP_STATUS=ERROR\n"
                    "VIVADO_MCP_BITSTREAM_STATUS=blocked\n"
                    "VIVADO_MCP_BITSTREAM_ERROR="
                    "Implementation must complete before bitstream generation\n"
                ),
                stderr="",
                args=("vivado",),
            )
        if self.mode == "failed_impl":
            raise VivadoExecutionError(
                "Vivado exited with code 1.",
                returncode=1,
                stdout=(
                    "VIVADO_MCP_STATUS=ERROR\n"
                    "VIVADO_MCP_BITSTREAM_STATUS=failed\n"
                    "VIVADO_MCP_BITSTREAM_ERROR="
                    "Implementation failed; cannot generate bitstream: "
                    "route_design ERROR\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=route_design ERROR\n"
                ),
                stderr="ERROR: [Common 17-69] Command failed\n",
            )
        if self.mode == "failed":
            raise VivadoExecutionError(
                "Vivado exited with code 1.",
                returncode=1,
                stdout=(
                    "VIVADO_MCP_STATUS=ERROR\n"
                    "VIVADO_MCP_BITSTREAM_STATUS=failed\n"
                    "VIVADO_MCP_BITSTREAM_ERROR=Bitstream generation failed: "
                    "write_bitstream ERROR\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=write_bitstream ERROR\n"
                    "ERROR: [Bitgen 20-1] write_bitstream failed\n"
                ),
                stderr="",
            )
        if self.mode == "missing_bit":
            return CommandResult(
                returncode=0,
                stdout=(
                    "VIVADO_MCP_STATUS=OK\n"
                    "VIVADO_MCP_BITSTREAM_STATUS=completed\n"
                    "VIVADO_MCP_BITSTREAM_TOP=counter\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=write_bitstream Complete!\n"
                ),
                stderr="",
                args=("vivado",),
            )
        if self.mode == "zero_byte":
            assert self.bit_path is not None
            self.bit_path.write_bytes(b"")
            return CommandResult(
                returncode=0,
                stdout=(
                    "VIVADO_MCP_STATUS=OK\n"
                    "VIVADO_MCP_BITSTREAM_STATUS=completed\n"
                    f"VIVADO_MCP_BITSTREAM_PATH={self.bit_path}\n"
                    "VIVADO_MCP_BITSTREAM_SIZE=0\n"
                    "VIVADO_MCP_BITSTREAM_TOP=counter\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=write_bitstream Complete!\n"
                ),
                stderr="",
                args=("vivado",),
            )
        if self.mode == "timeout":
            raise VivadoExecutionError(
                "Vivado timed out after 7200.0 seconds",
                stdout="still running write_bitstream\n",
                stderr="",
            )
        if self.mode == "malformed":
            return CommandResult(
                returncode=0,
                stdout="VIVADO_MCP_STATUS=OK\nVIVADO_MCP_BITSTREAM_STATUS=???\n",
                stderr="",
                args=("vivado",),
            )

        assert self.bit_path is not None
        if not self.bit_path.is_file():
            self.bit_path.parent.mkdir(parents=True, exist_ok=True)
            self.bit_path.write_bytes(b"BITSTREAM_FAKE_DATA_123456")
        size = self.bit_path.stat().st_size
        return CommandResult(
            returncode=0,
            stdout=(
                "VIVADO_MCP_STATUS=OK\n"
                "VIVADO_MCP_BITSTREAM_STATUS=completed\n"
                "VIVADO_MCP_BITSTREAM_TOP=counter\n"
                f"VIVADO_MCP_BITSTREAM_PATH={self.bit_path}\n"
                f"VIVADO_MCP_BITSTREAM_SIZE={size}\n"
                "VIVADO_MCP_IMPL_RUN_STATUS=write_bitstream Complete!\n"
            ),
            stderr="WARNING: [Bitgen 20-0] unused pin\n",
            args=("vivado",),
        )

    def _handle_status(self) -> CommandResult:
        if self.mode == "status_blocked":
            return CommandResult(
                returncode=0,
                stdout=(
                    "VIVADO_MCP_STATUS=OK\n"
                    "VIVADO_MCP_BITSTREAM_STATUS=blocked\n"
                    "VIVADO_MCP_BITSTREAM_ERROR=Implementation has not completed\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=opt_design Running\n"
                ),
                stderr="",
                args=("vivado",),
            )
        if self.mode == "status_not_started":
            return CommandResult(
                returncode=0,
                stdout=(
                    "VIVADO_MCP_STATUS=OK\n"
                    "VIVADO_MCP_BITSTREAM_STATUS=not_started\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=route_design Complete!\n"
                    "VIVADO_MCP_BITSTREAM_TOP=counter\n"
                ),
                stderr="",
                args=("vivado",),
            )
        if self.mode == "status_failed":
            return CommandResult(
                returncode=0,
                stdout=(
                    "VIVADO_MCP_STATUS=OK\n"
                    "VIVADO_MCP_BITSTREAM_STATUS=failed\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=write_bitstream ERROR\n"
                ),
                stderr="",
                args=("vivado",),
            )
        if self.mode == "status_malformed":
            return CommandResult(
                returncode=0,
                stdout=(
                    "VIVADO_MCP_STATUS=OK\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=weird opaque status\n"
                ),
                stderr="",
                args=("vivado",),
            )
        if self.mode == "path_traversal":
            return CommandResult(
                returncode=0,
                stdout=(
                    "VIVADO_MCP_STATUS=OK\n"
                    "VIVADO_MCP_BITSTREAM_STATUS=completed\n"
                    "VIVADO_MCP_BITSTREAM_PATH=/tmp/evil.bit\n"
                    "VIVADO_MCP_BITSTREAM_SIZE=99\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=write_bitstream Complete!\n"
                ),
                stderr="",
                args=("vivado",),
            )
        if self.stdout:
            return CommandResult(
                returncode=0,
                stdout=self.stdout,
                stderr=self.stderr,
                args=("vivado",),
            )
        if self.bit_path is not None and self.bit_path.is_file():
            size = self.bit_path.stat().st_size
            return CommandResult(
                returncode=0,
                stdout=(
                    "VIVADO_MCP_STATUS=OK\n"
                    "VIVADO_MCP_BITSTREAM_STATUS=completed\n"
                    "VIVADO_MCP_BITSTREAM_TOP=counter\n"
                    f"VIVADO_MCP_BITSTREAM_PATH={self.bit_path}\n"
                    f"VIVADO_MCP_BITSTREAM_SIZE={size}\n"
                    "VIVADO_MCP_IMPL_RUN_STATUS=write_bitstream Complete!\n"
                ),
                stderr="",
                args=("vivado",),
            )
        return CommandResult(
            returncode=0,
            stdout=(
                "VIVADO_MCP_STATUS=OK\n"
                "VIVADO_MCP_BITSTREAM_STATUS=not_started\n"
                "VIVADO_MCP_IMPL_RUN_STATUS=route_design Complete!\n"
            ),
            stderr="",
            args=("vivado",),
        )


def test_tcl_uses_write_bitstream_step(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    script = build_generate_bitstream_tcl(xpr_path=xpr)
    assert "launch_runs impl_1 -to_step write_bitstream" in script
    assert "wait_on_run impl_1" in script
    assert "Implementation must complete before bitstream generation" in script


def test_classify_bitstream_run_status() -> None:
    assert (
        classify_bitstream_run_status("write_bitstream Complete!") == STATUS_COMPLETED
    )
    assert classify_bitstream_run_status("route_design Complete!") == STATUS_NOT_STARTED
    assert classify_bitstream_run_status("write_bitstream Running") == "running"
    assert classify_bitstream_run_status("write_bitstream ERROR") == STATUS_FAILED
    assert classify_bitstream_run_status("opt_design Running") == "running"
    assert classify_bitstream_run_status("") == "unknown"
    assert (
        classify_bitstream_run_status(
            "route_design Complete!",
            bitstream_exists=True,
        )
        == STATUS_COMPLETED
    )
    parser = VivadoReportParser()
    assert parser.parse_bitstream_status("write_bitstream Complete!") == (
        STATUS_COMPLETED
    )


def test_successful_bitstream_generation(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    bit = _impl_bit_path(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="success", bit_path=bit))
    result = mgr.generate_bitstream(str(xpr))
    assert result.success is True
    assert result.status == STATUS_COMPLETED
    assert result.message == "Bitstream generated successfully"
    assert result.bitstream is not None
    assert result.bitstream["filename"] == "counter.bit"
    assert result.bitstream["size_bytes"] > 0
    assert Path(result.bitstream["path"]).is_file()
    assert result.warnings is not None


def test_successful_bitstream_status(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    bit = _impl_bit_path(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="success", bit_path=bit))
    status = mgr.get_bitstream_status(str(xpr))
    assert status.success is True
    assert status.status == STATUS_COMPLETED
    assert status.bitstream_exists is True
    assert status.path == str(bit.resolve())


def test_failed_bitstream_generation(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="failed"))
    result = mgr.generate_bitstream(str(xpr))
    assert result.success is False
    assert result.status == STATUS_FAILED
    assert "failed" in (result.message or "").lower()
    assert result.errors is not None


def test_blocked_generation(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="blocked"))
    result = mgr.generate_bitstream(str(xpr))
    assert result.success is False
    assert result.status == STATUS_BLOCKED
    assert result.reason == (
        "Implementation must complete before bitstream generation"
    )


def test_missing_implementation(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="missing_impl"))
    result = mgr.generate_bitstream(str(xpr))
    assert result.success is False
    assert result.status == STATUS_BLOCKED


def test_failed_implementation_blocks_or_fails(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="failed_impl"))
    # Fake returns exit 1 — Vivado runner would raise; simulate via mode that
    # returns non-OK markers without raising when Fake doesn't raise.
    # Our Fake returns CommandResult with returncode=1 but doesn't raise.
    # BitstreamManager treats STATUS != OK as failure.
    result = mgr.generate_bitstream(str(xpr))
    assert result.success is False
    assert result.status == STATUS_FAILED


def test_missing_bit_file(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="missing_bit"))
    result = mgr.generate_bitstream(str(xpr))
    assert result.success is False
    assert result.status == STATUS_FAILED
    assert "not found" in (result.message or "").lower()


def test_zero_byte_bitstream(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    bit = _impl_bit_path(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="zero_byte", bit_path=bit))
    result = mgr.generate_bitstream(str(xpr))
    assert result.success is False
    assert result.status == STATUS_FAILED
    assert "empty" in (result.message or "").lower() or "0" in (
        result.message or ""
    )


def test_valid_bitstream_path(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    bit = _impl_bit_path(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="success", bit_path=bit))
    path_result = mgr.get_bitstream_path(str(xpr))
    assert path_result.success is True
    assert path_result.status == STATUS_AVAILABLE
    assert path_result.path == str(bit.resolve())
    assert path_result.filename == "counter.bit"
    assert path_result.size_bytes is not None and path_result.size_bytes > 0


def test_bitstream_path_not_available(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="status_not_started"))
    path_result = mgr.get_bitstream_path(str(xpr))
    assert path_result.success is True
    assert path_result.status == STATUS_NOT_AVAILABLE
    assert path_result.path is None


def test_invalid_path_rejected(tmp_path: Path) -> None:
    project_dir = tmp_path
    outside = tmp_path.parent / "outside.bit"
    outside.write_bytes(b"nope")
    assert _validate_bitstream_path(project_dir, outside) is None


def test_path_traversal_rejected(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    evil = tmp_path / ".." / "escape.bit"
    # Create a file outside via relative traversal string reported by Vivado
    outside = (tmp_path / ".." / "escape.bit").resolve()
    outside.write_bytes(b"evil")
    mgr = BitstreamManager(
        FakeVivado(
            mode="path_traversal",
            stdout=(
                "VIVADO_MCP_STATUS=OK\n"
                "VIVADO_MCP_BITSTREAM_STATUS=completed\n"
                f"VIVADO_MCP_BITSTREAM_PATH={evil}\n"
                "VIVADO_MCP_BITSTREAM_SIZE=4\n"
                "VIVADO_MCP_IMPL_RUN_STATUS=write_bitstream Complete!\n"
            ),
        )
    )
    # Force status handler path for get_bitstream_path
    mgr.vivado.mode = "path_traversal"  # type: ignore[attr-defined]
    path_result = mgr.get_bitstream_path(str(xpr))
    assert path_result.success is True
    assert path_result.status == STATUS_NOT_AVAILABLE
    assert path_result.path is None


def test_timeout(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="timeout"))
    result = mgr.generate_bitstream(str(xpr))
    assert result.success is False
    assert result.status == STATUS_TIMEOUT
    assert "timeout" in (result.message or "").lower()


def test_malformed_vivado_status(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="status_malformed"))
    status = mgr.get_bitstream_status(str(xpr))
    assert status.success is True
    assert status.status == "unknown"


def test_status_blocked(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="status_blocked"))
    status = mgr.get_bitstream_status(str(xpr))
    assert status.success is True
    assert status.status == STATUS_BLOCKED
    assert status.reason == "Implementation has not completed"
    assert status.bitstream_exists is False


def test_filesystem_error_on_generate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xpr = _make_project(tmp_path)
    bit = _impl_bit_path(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="success", bit_path=bit))

    monkeypatch.setattr(
        "vivado_mcp.bitstream._validate_bitstream_path",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("Permission denied")),
    )
    result = mgr.generate_bitstream(str(xpr))
    assert result.success is False
    assert result.status == STATUS_FAILED
    assert "filesystem" in (result.message or "").lower() or "Permission" in (
        result.message or ""
    )


def test_get_bitstream_status_not_started_without_bit(tmp_path: Path) -> None:
    xpr = _make_project(tmp_path)
    mgr = BitstreamManager(FakeVivado(mode="status_not_started"))
    status = mgr.get_bitstream_status(str(xpr))
    assert status.success is True
    assert status.status == STATUS_NOT_STARTED
    assert status.bitstream_exists is False
