"""MCP server entrypoint for Vivado MCP.

Tool handlers stay thin: they delegate Vivado-specific work to the Vivado
abstraction / project manager and return structured results.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server import MCPServer

from vivado_mcp import __version__
from vivado_mcp.config import Config
from vivado_mcp.projects import ProjectManager
from vivado_mcp.vivado import Vivado

logger = logging.getLogger(__name__)

mcp = MCPServer(
    name="vivado-mcp",
    version=__version__,
    instructions=(
        "MCP server for AMD/Xilinx Vivado. Use get_vivado_version to verify "
        "Vivado is reachable, then create_project / open_project / close_project "
        "for project management. Users must provide their own licensed Vivado "
        "installation. There is no generic Tcl or shell execution tool."
    ),
)


def _build_vivado() -> Vivado:
    """Construct a Vivado client from the current process environment."""
    return Vivado(Config.from_env())


def _build_project_manager() -> ProjectManager:
    return ProjectManager(_build_vivado())


@mcp.tool()
def get_vivado_version() -> dict[str, Any]:
    """Detect the installed AMD/Xilinx Vivado version.

    Call this tool to check whether Vivado is available before running any
    FPGA project, simulation, synthesis, or implementation workflow.

    Returns structured information including whether Vivado is installed,
    the version string, the resolved executable path, and the host platform.
    If Vivado cannot be found, returns ``installed: false`` with guidance on
    setting the ``VIVADO_PATH`` environment variable.
    """
    logger.info("Tool invoked: get_vivado_version")
    info = _build_vivado().get_version()
    return info.to_dict()


@mcp.tool()
def create_project(name: str, path: str, part: str) -> dict[str, Any]:
    """Create a new Vivado project in batch mode.

    Args:
        name: Project name (letters, digits, underscore; must start with a
            letter or underscore).
        path: Parent directory for the project. The project is created at
            ``{path}/{name}/{name}.xpr``. Directories are created if needed.
            Existing projects are never overwritten.
        part: Vivado FPGA part string, for example ``xc7a35tcpg236-1``.

    Returns structured success/error data. Does not open the Vivado GUI.
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
    """Open an existing Vivado project (.xpr) in batch mode to verify it.

    Args:
        path: Path to a ``.xpr`` file, or to a project directory containing one.

    Opens the project with Vivado Tcl, reports structured metadata, then
    closes it so no GUI/batch process is left running.
    """
    logger.info("Tool invoked: open_project path=%s", path)
    return _build_project_manager().open_project(path=path).to_dict()


@mcp.tool()
def close_project(path: str) -> dict[str, Any]:
    """Close a Vivado project cleanly using batch-mode Tcl.

    Args:
        path: Path to a ``.xpr`` file, or to a project directory containing one.

    Opens the project if needed, closes it with Vivado Tcl, and exits batch
    mode so no Vivado GUI process remains.
    """
    logger.info("Tool invoked: close_project path=%s", path)
    return _build_project_manager().close_project(path=path).to_dict()


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
