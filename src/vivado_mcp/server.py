"""MCP server entrypoint for Vivado MCP.

Tool handlers stay thin: they delegate to project/source/simulation/synthesis
managers and the Vivado abstraction, returning structured results only.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server import MCPServer

from vivado_mcp import __version__
from vivado_mcp.config import Config
from vivado_mcp.projects import ProjectManager
from vivado_mcp.simulation import SimulationManager
from vivado_mcp.sources import SourceManager
from vivado_mcp.synthesis import SynthesisManager
from vivado_mcp.vivado import Vivado

logger = logging.getLogger(__name__)

mcp = MCPServer(
    name="vivado-mcp",
    version=__version__,
    instructions=(
        "MCP server for AMD/Xilinx Vivado. Use get_vivado_version first, then "
        "create_project / open_project / close_project for projects, "
        "create_rtl_file / add_source / remove_source / list_sources for RTL, "
        "create_testbench / run_simulation / get_simulation_status for RTL "
        "simulation, and run_synthesis / get_utilization / get_timing for "
        "synthesis reports. Add testbenches with add_source(..., fileset='sim_1'). "
        "Users must provide their own licensed Vivado installation. There is "
        "no generic Tcl or shell execution tool."
    ),
)


def _build_vivado() -> Vivado:
    return Vivado(Config.from_env())


def _build_project_manager() -> ProjectManager:
    return ProjectManager(_build_vivado())


def _build_source_manager() -> SourceManager:
    return SourceManager(_build_vivado())


def _build_simulation_manager() -> SimulationManager:
    return SimulationManager(_build_vivado())


def _build_synthesis_manager() -> SynthesisManager:
    return SynthesisManager(_build_vivado())


@mcp.tool()
def get_vivado_version() -> dict[str, Any]:
    """Detect the installed AMD/Xilinx Vivado version.

    Call this before project or RTL workflows. Returns structured install
    information, or ``installed: false`` with guidance if Vivado is missing.
    """
    logger.info("Tool invoked: get_vivado_version")
    return _build_vivado().get_version().to_dict()


@mcp.tool()
def create_project(name: str, path: str, part: str) -> dict[str, Any]:
    """Create a new Vivado project in batch mode.

    Args:
        name: Project name (identifier characters only).
        path: Parent directory for the project.
        part: FPGA part string, for example ``xc7a35tcpg236-1``.

    Never overwrites an existing project. Does not open the Vivado GUI.
    """
    logger.info(
        "Tool invoked: create_project name=%s path=%s part=%s", name, path, part
    )
    return (
        _build_project_manager()
        .create_project(name=name, path=path, part=part)
        .to_dict()
    )


@mcp.tool()
def open_project(path: str) -> dict[str, Any]:
    """Open/verify an existing Vivado project (.xpr) in batch mode, then close it.

    Args:
        path: Path to a ``.xpr`` file or a project directory containing one.
    """
    logger.info("Tool invoked: open_project path=%s", path)
    return _build_project_manager().open_project(path=path).to_dict()


@mcp.tool()
def close_project(path: str) -> dict[str, Any]:
    """Close a Vivado project cleanly using batch-mode Tcl.

    Args:
        path: Path to a ``.xpr`` file or a project directory containing one.
    """
    logger.info("Tool invoked: close_project path=%s", path)
    return _build_project_manager().close_project(path=path).to_dict()


@mcp.tool()
def create_rtl_file(
    project_path: str,
    filename: str,
    code: str,
    language: str = "verilog",
) -> dict[str, Any]:
    """Create a Verilog/SystemVerilog file under the project's ``rtl/`` folder.

    Args:
        project_path: Path to the ``.xpr`` or project directory.
        filename: Basename only (for example ``counter.v``). No directories or
            ``..`` segments. Extension may be omitted and inferred from
            ``language``.
        code: Exact RTL text to write. It is not executed, parsed, or modified.
        language: ``verilog`` (``.v``) or ``systemverilog`` (``.sv``).

    Does not add the file to the Vivado project. Call ``add_source`` afterward.
    Refuses to overwrite an existing file.
    """
    logger.info(
        "Tool invoked: create_rtl_file project=%s filename=%s language=%s",
        project_path,
        filename,
        language,
    )
    return (
        _build_source_manager()
        .create_rtl_file(
            project_path=project_path,
            filename=filename,
            code=code,
            language=language,
        )
        .to_dict()
    )


@mcp.tool()
def add_source(
    project_path: str,
    source_path: str,
    fileset: str = "sources_1",
) -> dict[str, Any]:
    """Add an existing ``.v`` / ``.sv`` file to a Vivado project fileset.

    Args:
        project_path: Path to the ``.xpr`` or project directory.
        source_path: Absolute or relative path to an existing RTL file.
        fileset: ``sources_1`` for design RTL (default) or ``sim_1`` for
            simulation / testbench sources.

    Uses Vivado ``add_files`` and updates compile order. Does not expose
    arbitrary Tcl.
    """
    logger.info(
        "Tool invoked: add_source project=%s source=%s fileset=%s",
        project_path,
        source_path,
        fileset,
    )
    return (
        _build_source_manager()
        .add_source(
            project_path=project_path,
            source_path=source_path,
            fileset=fileset,
        )
        .to_dict()
    )


@mcp.tool()
def remove_source(project_path: str, source_path: str) -> dict[str, Any]:
    """Remove a source from a Vivado project without deleting the file on disk.

    Args:
        project_path: Path to the ``.xpr`` or project directory.
        source_path: Path of the source currently in the project.

    Removes the file from the project file set only. The physical RTL file is
    left intact.
    """
    logger.info(
        "Tool invoked: remove_source project=%s source=%s",
        project_path,
        source_path,
    )
    return (
        _build_source_manager()
        .remove_source(project_path=project_path, source_path=source_path)
        .to_dict()
    )


@mcp.tool()
def list_sources(project_path: str) -> dict[str, Any]:
    """List design sources in a Vivado project.

    Args:
        project_path: Path to the ``.xpr`` or project directory.

    Returns structured entries with path, type, and library when available.
    """
    logger.info("Tool invoked: list_sources project=%s", project_path)
    return _build_source_manager().list_sources(project_path=project_path).to_dict()


@mcp.tool()
def create_testbench(
    project_path: str,
    filename: str,
    code: str,
    language: str = "verilog",
) -> dict[str, Any]:
    """Create a Verilog/SystemVerilog testbench under the project's ``sim/`` folder.

    Args:
        project_path: Path to the ``.xpr`` or project directory.
        filename: Basename only (for example ``counter_tb.v``). No directories
            or ``..`` segments.
        code: Exact testbench text to write. It is not executed or modified.
        language: ``verilog`` (``.v``) or ``systemverilog`` (``.sv``).

    Does not register the file in Vivado. Call ``add_source`` with
    ``fileset='sim_1'`` afterward. Refuses to overwrite an existing file.
    """
    logger.info(
        "Tool invoked: create_testbench project=%s filename=%s language=%s",
        project_path,
        filename,
        language,
    )
    return (
        _build_simulation_manager()
        .create_testbench(
            project_path=project_path,
            filename=filename,
            code=code,
            language=language,
        )
        .to_dict()
    )


@mcp.tool()
def run_simulation(
    project_path: str,
    top_module: str | None = None,
    simulation_time: str = "100ns",
) -> dict[str, Any]:
    """Run RTL behavioral simulation with Vivado XSim in batch mode.

    Args:
        project_path: Path to the ``.xpr`` or project directory.
        top_module: Optional simulation top (testbench) module name. When
            omitted, uses the current ``sim_1`` top property.
        simulation_time: Runtime such as ``100ns``, ``1us``, or ``1ms``.

    Opens the project, configures XSim, launches behavioral simulation, then
    closes cleanly. Does not open the Vivado GUI. Distinguishes compile,
    elaborate, runtime, and assertion failures when possible.
    """
    logger.info(
        "Tool invoked: run_simulation project=%s top=%s time=%s",
        project_path,
        top_module,
        simulation_time,
    )
    return (
        _build_simulation_manager()
        .run_simulation(
            project_path=project_path,
            top_module=top_module,
            simulation_time=simulation_time,
        )
        .to_dict()
    )


@mcp.tool()
def get_simulation_status(project_path: str) -> dict[str, Any]:
    """Return structured status for the most recent simulation on a project.

    Args:
        project_path: Path to the ``.xpr`` or project directory.

    If no simulation has been run, returns ``status: not_run`` rather than
    raising an exception.
    """
    logger.info("Tool invoked: get_simulation_status project=%s", project_path)
    return (
        _build_simulation_manager()
        .get_simulation_status(project_path=project_path)
        .to_dict()
    )


@mcp.tool()
def run_synthesis(project_path: str) -> dict[str, Any]:
    """Run Vivado synthesis for a project in batch mode.

    Args:
        project_path: Path to the ``.xpr`` or project directory.

    Opens the project, launches ``synth_1``, waits for completion, writes
    utilization and timing-summary reports under ``.vivado_mcp/reports/``,
    then closes cleanly. Does not open the Vivado GUI.
    """
    logger.info("Tool invoked: run_synthesis project=%s", project_path)
    return (
        _build_synthesis_manager()
        .run_synthesis(project_path=project_path)
        .to_dict()
    )


@mcp.tool()
def get_utilization(project_path: str) -> dict[str, Any]:
    """Return structured post-synthesis resource utilization.

    Args:
        project_path: Path to the ``.xpr`` or project directory.

    Parses Vivado ``report_utilization`` output. Missing device resources are
    returned as ``null`` rather than failing the whole request. Requires a
    completed synthesis run.
    """
    logger.info("Tool invoked: get_utilization project=%s", project_path)
    return (
        _build_synthesis_manager()
        .get_utilization(project_path=project_path)
        .to_dict()
    )


@mcp.tool()
def get_timing(project_path: str) -> dict[str, Any]:
    """Return structured post-synthesis timing summary if available.

    Args:
        project_path: Path to the ``.xpr`` or project directory.

    Post-synthesis timing is estimated and is **not** final implementation
    timing. When constraints are missing, returns ``status: not_available``
    with a clear reason rather than raising.
    """
    logger.info("Tool invoked: get_timing project=%s", project_path)
    return (
        _build_synthesis_manager()
        .get_timing(project_path=project_path)
        .to_dict()
    )


def main() -> None:
    """Run the Vivado MCP server over stdio."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger.info("Starting vivado-mcp %s", __version__)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
