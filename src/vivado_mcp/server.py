"""MCP server entrypoint for Vivado MCP.

Tool handlers stay thin: they delegate to project/source managers and the
Vivado abstraction, returning structured results only.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server import MCPServer

from vivado_mcp import __version__
from vivado_mcp.config import Config
from vivado_mcp.projects import ProjectManager
from vivado_mcp.sources import SourceManager
from vivado_mcp.vivado import Vivado

logger = logging.getLogger(__name__)

mcp = MCPServer(
    name="vivado-mcp",
    version=__version__,
    instructions=(
        "MCP server for AMD/Xilinx Vivado. Use get_vivado_version first, then "
        "create_project / open_project / close_project for projects, and "
        "create_rtl_file / add_source / remove_source / list_sources for RTL. "
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
def add_source(project_path: str, source_path: str) -> dict[str, Any]:
    """Add an existing ``.v`` / ``.sv`` file to a Vivado project.

    Args:
        project_path: Path to the ``.xpr`` or project directory.
        source_path: Absolute or relative path to an existing RTL file.

    Uses Vivado ``add_files`` and updates compile order. Does not expose
    arbitrary Tcl.
    """
    logger.info(
        "Tool invoked: add_source project=%s source=%s", project_path, source_path
    )
    return (
        _build_source_manager()
        .add_source(project_path=project_path, source_path=source_path)
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
