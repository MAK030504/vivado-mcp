"""MCP server entrypoint for Vivado MCP.

Tool handlers stay thin: they delegate Vivado-specific work to
:class:`vivado_mcp.vivado.Vivado` and return structured results.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server import MCPServer

from vivado_mcp import __version__
from vivado_mcp.config import Config
from vivado_mcp.vivado import Vivado

logger = logging.getLogger(__name__)

mcp = MCPServer(
    name="vivado-mcp",
    version=__version__,
    instructions=(
        "MCP server for AMD/Xilinx Vivado. Use get_vivado_version to verify "
        "that Vivado is installed and reachable before attempting FPGA flows. "
        "Users must provide their own licensed Vivado installation."
    ),
)


def _build_vivado() -> Vivado:
    """Construct a Vivado client from the current process environment."""
    return Vivado(Config.from_env())


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
