"""Integration tests for bitstream generation (requires Vivado)."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from vivado_mcp.bitstream import (
    STATUS_AVAILABLE,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_NOT_STARTED,
    BitstreamManager,
)
from vivado_mcp.config import Config
from vivado_mcp.implementation import (
    STATUS_COMPLETED as IMPL_COMPLETED,
)
from vivado_mcp.implementation import ImplementationManager
from vivado_mcp.projects import ProjectManager
from vivado_mcp.reports import is_environment_impl_failure
from vivado_mcp.sources import SourceManager
from vivado_mcp.synthesis import STATUS_COMPLETED as SYNTH_COMPLETED
from vivado_mcp.synthesis import SynthesisManager
from vivado_mcp.vivado import Vivado

COUNTER_RTL = """\
module counter(
  input wire clk,
  input wire rst,
  output reg [3:0] count
);
  always @(posedge clk) begin
    if (rst)
      count <= 4'b0000;
    else
      count <= count + 1'b1;
  end
endmodule
"""


def _vivado_available() -> bool:
    try:
        info = Vivado(Config.from_env()).get_version()
    except Exception:
        return False
    return bool(info.installed)


def _cleanup_project_tree(parent: Path, name: str) -> None:
    shutil.rmtree(parent / name, ignore_errors=True)
    for leftover in parent.glob(f"{name}*"):
        if leftover.is_dir():
            shutil.rmtree(leftover, ignore_errors=True)
        else:
            leftover.unlink(missing_ok=True)
    for folder in ("rtl", "sim", ".vivado_mcp"):
        shutil.rmtree(parent / folder, ignore_errors=True)


def _skip_if_environment_failure(impl_result: object) -> None:
    """Skip when Vivado host lacks Implementation license or runs out of memory."""
    failure_kind = getattr(impl_result, "failure_kind", None)
    log_summary = getattr(impl_result, "log_summary", None) or ""
    message = getattr(impl_result, "message", None) or ""
    combined = f"{message}\n{log_summary}"
    if is_environment_impl_failure(failure_kind, combined):
        pytest.skip(
            "Vivado implementation unavailable on this host "
            f"(failure_kind={failure_kind!r}). "
            "Check Implementation license for the device and free memory, "
            "then re-run."
        )


@pytest.mark.integration
def test_real_vivado_bitstream_blocked_without_impl(tmp_path: Path) -> None:
    """Bitstream generation must refuse to run before implementation completes."""
    if not _vivado_available():
        pytest.skip("Vivado is not installed on this machine")

    vivado = Vivado(Config.from_env())
    projects = ProjectManager(vivado)
    sources = SourceManager(vivado)
    bitstream = BitstreamManager(vivado)

    parent = tmp_path / "vivado_mcp_bit_blocked_it"
    parent.mkdir()
    project_name = "bit_blocked"
    project_path = ""

    try:
        created = projects.create_project(
            name=project_name,
            path=str(parent),
            part="xc7a35tcpg236-1",
        )
        assert created.success is True, created.error
        assert created.project is not None
        project_path = created.project.xpr or created.project.path

        rtl = sources.create_rtl_file(
            project_path=str(project_path),
            filename="counter.v",
            code=COUNTER_RTL,
            language="verilog",
        )
        assert rtl.success is True, rtl.error
        assert rtl.source_path is not None

        added = sources.add_source(
            project_path=str(project_path),
            source_path=rtl.source_path,
            fileset="sources_1",
        )
        assert added.success is True, added.error

        blocked = bitstream.generate_bitstream(str(project_path))
        assert blocked.success is False
        assert blocked.status == STATUS_BLOCKED
        assert "Implementation must complete" in (
            blocked.reason or blocked.message or ""
        )

        status = bitstream.get_bitstream_status(str(project_path))
        assert status.success is True
        assert status.status == STATUS_BLOCKED
        assert status.bitstream_exists is False
    finally:
        if project_path:
            projects.close_project(str(project_path))
        _cleanup_project_tree(parent, project_name)


@pytest.mark.integration
def test_real_vivado_bitstream_workflow(tmp_path: Path) -> None:
    """Temporary counter project: synth → impl → bitstream → status/path → cleanup.

    Does not modify any permanent project such as mcp_counter.
    """
    if not _vivado_available():
        pytest.skip("Vivado is not installed on this machine")

    vivado = Vivado(Config.from_env())
    projects = ProjectManager(vivado)
    sources = SourceManager(vivado)
    synthesis = SynthesisManager(vivado)
    implementation = ImplementationManager(vivado)
    bitstream = BitstreamManager(vivado)

    parent = tmp_path / "vivado_mcp_bit_it"
    parent.mkdir()
    project_name = "bit_demo"
    project_path = ""

    try:
        created = projects.create_project(
            name=project_name,
            path=str(parent),
            part="xc7a35tcpg236-1",
        )
        assert created.success is True, created.error
        assert created.project is not None
        project_path = created.project.xpr or created.project.path

        rtl = sources.create_rtl_file(
            project_path=str(project_path),
            filename="counter.v",
            code=COUNTER_RTL,
            language="verilog",
        )
        assert rtl.success is True, rtl.error
        assert rtl.source_path is not None

        added = sources.add_source(
            project_path=str(project_path),
            source_path=rtl.source_path,
            fileset="sources_1",
        )
        assert added.success is True, added.error

        synth = synthesis.run_synthesis(str(project_path))
        assert synth.success is True, (synth.error, synth.log_summary)
        assert synth.status == SYNTH_COMPLETED
        time.sleep(1.5)

        impl = implementation.run_implementation(str(project_path))
        if not impl.success:
            _skip_if_environment_failure(impl)
            time.sleep(3.0)
            impl = implementation.run_implementation(str(project_path))
            if not impl.success:
                _skip_if_environment_failure(impl)
        assert impl.success is True, (impl.error, impl.log_summary, impl.failure_kind)
        assert impl.status == IMPL_COMPLETED
        time.sleep(1.5)

        before = bitstream.get_bitstream_status(str(project_path))
        assert before.success is True
        assert before.status in {STATUS_NOT_STARTED, STATUS_COMPLETED}

        bit = bitstream.generate_bitstream(str(project_path))
        assert bit.success is True, (bit.error, bit.log_summary)
        assert bit.status == STATUS_COMPLETED
        assert bit.bitstream is not None
        bit_path = Path(bit.bitstream["path"])
        assert bit_path.is_file()
        assert bit.bitstream["size_bytes"] > 0
        assert bit_path.stat().st_size > 0

        status = bitstream.get_bitstream_status(str(project_path))
        assert status.success is True
        assert status.status == STATUS_COMPLETED
        assert status.bitstream_exists is True
        assert status.path is not None
        assert Path(status.path).resolve() == bit_path.resolve()

        path_result = bitstream.get_bitstream_path(str(project_path))
        assert path_result.success is True
        assert path_result.status == STATUS_AVAILABLE
        assert path_result.path is not None
        assert Path(path_result.path).resolve() == bit_path.resolve()
        assert path_result.size_bytes is not None and path_result.size_bytes > 0
    finally:
        if project_path:
            projects.close_project(str(project_path))
        _cleanup_project_tree(parent, project_name)
