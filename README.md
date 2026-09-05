# Vivado MCP

**Vivado MCP** is an open-source [Model Context Protocol](https://modelcontextprotocol.io)
server that lets AI clients such as Cursor interact with
[AMD/Xilinx Vivado](https://www.amd.com/en/products/software/adaptive-socs-and-fpgas/vivado.html)
programmatically.

It does **not** automate the Vivado GUI. All Vivado interaction goes through
Vivado's official Tcl / batch command interface.

```text
AI Client (Cursor, etc.)
        │
        ▼
   Vivado MCP Server
        │
        ▼
  Vivado abstraction layer
        │
        ▼
     Vivado Tcl / batch CLI
        │
        ▼
   AMD/Xilinx Vivado
```

You must have your own valid Vivado installation and license. This project only
talks to whatever Vivado executable you configure.

## Current capabilities (Milestone 1)

| Tool | Description |
|------|-------------|
| `get_vivado_version` | Locate Vivado, run it in a non-GUI-safe way, and return structured version information |

That is the full MCP surface for this release. Project creation, RTL editing,
simulation, synthesis, implementation, bitstream generation, and report
retrieval are intentionally **not** implemented yet.

## Requirements

- Python 3.11+
- An MCP-compatible client (for example Cursor)
- A local AMD/Xilinx Vivado installation (Windows or Linux)

## Installation

```bash
git clone https://github.com/mak030504/vivado-mcp.git
cd vivado-mcp
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Configuration

Do **not** edit Python source to point at Vivado. Configure via environment
variables (or your MCP client `env` block):

| Variable | Purpose |
|----------|---------|
| `VIVADO_PATH` | Absolute path to the Vivado executable |
| `VIVADO_VERSION` | Optional preferred version for auto-detection (e.g. `2018.2`) |
| `VIVADO_WORKSPACE` | Optional default workspace/project directory (reserved for later milestones) |

### Executable path examples

Linux:

```bash
export VIVADO_PATH=/tools/Xilinx/Vivado/2018.2/bin/vivado
export VIVADO_VERSION=2018.2
```

Windows (PowerShell):

```powershell
$env:VIVADO_PATH = "C:\Xilinx\Vivado\2018.2\bin\vivado.bat"
$env:VIVADO_VERSION = "2018.2"
```

**Windows tip:** the Start Menu path
`...\Start Menu\Programs\Xilinx Design Tools\Vivado 2018.2` is a shortcut
folder, not the executable. Point `VIVADO_PATH` at `vivado.bat` instead
(usually `C:\Xilinx\Vivado\2018.2\bin\vivado.bat`). Right-click the Start Menu
entry → More → Open file location → Properties → copy **Target**.

If `VIVADO_PATH` is unset, Vivado MCP tries:

1. `vivado` / `vivado.bat` on `PATH`
2. Common install roots for versioned Vivado directories (no single hard-coded path)

## How to run the MCP server

After installation:

```bash
vivado-mcp
# or
python -m vivado_mcp
```

The server speaks MCP over **stdio** (default for Cursor and most local clients).

## Configure in Cursor

Add a server entry to your Cursor MCP settings. Example:

```json
{
  "mcpServers": {
    "vivado": {
      "command": "python",
      "args": ["-m", "vivado_mcp"],
      "env": {
        "VIVADO_PATH": "C:\\Xilinx\\Vivado\\2018.2\\bin\\vivado.bat",
        "VIVADO_VERSION": "2018.2"
      }
    }
  }
}
```

Do **not** set `VIVADO_PATH` to the Start Menu folder
(`...\Xilinx Design Tools\Vivado 2018.2`). Use `vivado.bat` under your Xilinx
install, typically `C:\Xilinx\Vivado\2018.2\bin\vivado.bat`.

See also [`examples/cursor_mcp_config.json`](examples/cursor_mcp_config.json).

Use the Python interpreter where `vivado-mcp` is installed. On Windows, point
`VIVADO_PATH` at `vivado.bat` when that is your installer's launcher.

## Verify that Vivado is detected

### From an AI client

Ask the agent to call `get_vivado_version`. A successful result looks like:

```json
{
  "installed": true,
  "version": "2018.2",
  "executable": "C:\\Xilinx\\Vivado\\2018.2\\bin\\vivado.bat",
  "platform": "windows",
  "error": null,
  "message": null
}
```

If Vivado is missing, you get a structured failure with guidance to set
`VIVADO_PATH` — not a raw traceback dump.

### From the command line

```bash
python -c "from vivado_mcp.vivado import Vivado; print(Vivado().get_version())"
```

### Run the test suite

```bash
pytest
```

Unit tests do **not** require Vivado. An optional integration test is skipped
automatically when Vivado is not installed:

```bash
pytest -m integration
```

## Architecture

| Module | Responsibility |
|--------|----------------|
| `server.py` | MCP tool surface only — thin wrappers |
| `vivado.py` | Locate / validate / invoke Vivado; parse structured results |
| `config.py` | Environment-based configuration |
| `errors.py` | Typed error hierarchy |

MCP handlers never spawn subprocesses directly. There is intentionally **no**
generic `execute_tcl` / `execute_command` MCP tool. Future tools will expose
controlled Vivado operations only.

## Current limitations

- Only `get_vivado_version` is implemented
- No project, RTL, XDC, simulation, synthesis, implementation, or bitstream tools yet
- macOS is not a supported Vivado host target
- Auto-detection covers common install layouts; unusual installs should set `VIVADO_PATH`
- Long-running Vivado flows and rich report parsing are not part of this milestone

## Roadmap

1. **Milestone 1 (this release):** Vivado discovery and version reporting
2. **Milestone 2:** Project create/open and RTL source add/remove
3. **Milestone 3:** XDC constraint management
4. **Milestone 4:** Simulation
5. **Milestone 5:** Synthesis, implementation, bitstream
6. **Milestone 6:** Timing / utilization / message reports and debug helpers
7. **Later:** Higher-level agentic RTL/FPGA workflows on top of the same abstraction

## Security

- No unrestricted shell execution through MCP
- No generic Tcl execution tool in this release
- Filesystem paths are validated before use
- This project does not implement or assist with license, DRM, or activation bypasses

## Development

```bash
pip install -e ".[dev]"
pytest
python -m vivado_mcp  # starts stdio MCP server
```

## License

MIT — see [LICENSE](LICENSE).
