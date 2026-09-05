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

**Windows tip:** you may set `VIVADO_PATH` to the Start Menu folder
`...\Start Menu\Programs\Xilinx Design Tools\Vivado 2018.2`. Vivado MCP will
treat that as a version hint and try to resolve
`C:\Xilinx\Vivado\2018.2\bin\vivado.bat`. For the most reliable setup, point
`VIVADO_PATH` at `vivado.bat` directly.

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

On Windows, set `command` to the **full path** of `python.exe` from the
environment where you installed `vivado-mcp`. Bare `python` often fails inside
Cursor with `The system cannot find the path specified`.

```json
{
  "mcpServers": {
    "vivado": {
      "command": "C:\\Users\\HP\\path\\to\\vivado-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "vivado_mcp"],
      "env": {
        "VIVADO_PATH": "C:\\Users\\HP\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Xilinx Design Tools\\Vivado 2018.2",
        "VIVADO_VERSION": "2018.2"
      }
    }
  }
}
```

Find the correct interpreter in PowerShell:

```powershell
python -c "import sys; print(sys.executable)"
python -c "import vivado_mcp; print(vivado_mcp.__file__)"
```

That Start Menu folder is accepted as a version hint and resolved to
`vivado.bat` when possible (usually `C:\Xilinx\Vivado\2018.2\bin\vivado.bat`).

See [`examples/README.md`](examples/README.md) for Windows troubleshooting.

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
