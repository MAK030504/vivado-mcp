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
  ProjectManager / Vivado abstraction
        │
        ▼
     Vivado Tcl / batch CLI
        │
        ▼
   AMD/Xilinx Vivado
```

You must have your own valid Vivado installation and license. This project only
talks to whatever Vivado executable you configure.

## Current capabilities (Milestone 2)

| Tool | Description |
|------|-------------|
| `get_vivado_version` | Locate Vivado and return structured version information |
| `create_project` | Create a new Vivado project for a given FPGA part |
| `open_project` | Open/verify an existing `.xpr` project in batch mode |
| `close_project` | Close a project cleanly via batch-mode Tcl |

Not implemented yet: RTL source management, XDC constraints, simulation,
synthesis, implementation, bitstream generation, timing/utilization reports,
or arbitrary Tcl execution.

## Requirements

- Python 3.11+
- An MCP-compatible client (for example Cursor)
- A local AMD/Xilinx Vivado installation (**Windows** or **Linux**)

## Installation

### Windows (PowerShell)

```powershell
git clone https://github.com/MAK030504/vivado-mcp.git
cd C:\Users\HP\vivado-mcp
git checkout cursor/vivado-mcp-milestone-2-c381
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
pip install -e .
python -c "import vivado_mcp; print(vivado_mcp.__file__)"
```

### Linux / macOS

```bash
git clone https://github.com/MAK030504/vivado-mcp.git
cd vivado-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

Do **not** edit Python source to point at Vivado. Configure via environment
variables (or your MCP client `env` block):

| Variable | Purpose |
|----------|---------|
| `VIVADO_PATH` | Absolute path to the Vivado executable (`vivado.bat` / `vivado`) |
| `VIVADO_VERSION` | Optional preferred version for auto-detection (e.g. `2018.2`) |
| `VIVADO_WORKSPACE` | Optional default workspace directory (reserved for later use) |

### Windows example

```powershell
$env:VIVADO_PATH = "D:\Softwares\Vivado\2018.2\bin\vivado.bat"
$env:VIVADO_VERSION = "2018.2"
```

## Run the MCP server

```bash
vivado-mcp
# or
python -m vivado_mcp
```

## Configure in Cursor

```json
{
  "mcpServers": {
    "vivado": {
      "command": "C:\\Users\\HP\\vivado-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "vivado_mcp"],
      "env": {
        "VIVADO_PATH": "D:\\Softwares\\Vivado\\2018.2\\bin\\vivado.bat",
        "VIVADO_VERSION": "2018.2"
      }
    }
  }
}
```

On Windows, `command` must be the full path to the venv `python.exe` where
`vivado-mcp` is installed.

## Tool usage

### `get_vivado_version`

Ask the agent to call `get_vivado_version`.

```json
{
  "installed": true,
  "version": "2018.2",
  "executable": "D:\\Softwares\\Vivado\\2018.2\\bin\\vivado.bat",
  "platform": "windows",
  "error": null,
  "message": null
}
```

### `create_project`

Creates `{path}/{name}/{name}.xpr` for the given FPGA part. Never overwrites
an existing project.

Example arguments:

- `name`: `"counter"`
- `path`: `"C:\\Users\\User Name\\Documents\\Vivado Projects"`
- `part`: `"xc7a35tcpg236-1"`

Success:

```json
{
  "success": true,
  "project": {
    "name": "counter",
    "path": ".../counter",
    "part": "xc7a35tcpg236-1",
    "xpr": ".../counter/counter.xpr"
  },
  "vivado_version": "2018.2",
  "message": "Created Vivado project 'counter'."
}
```

Error (already exists):

```json
{
  "success": false,
  "error": {
    "type": "ProjectAlreadyExistsError",
    "code": "project_already_exists",
    "message": "A Vivado project already exists at ..."
  }
}
```

### `open_project`

Opens an existing `.xpr` (or a project directory containing one) in batch mode,
returns metadata, then closes so no GUI process remains.

### `close_project`

Opens the project if needed, closes it with Vivado Tcl, and exits batch mode.

## Architecture

| Module | Responsibility |
|--------|----------------|
| `server.py` | Thin MCP tool wrappers |
| `projects.py` | Project create/open/close orchestration |
| `tcl.py` | Safe Tcl script generation / path quoting |
| `vivado.py` | Locate / validate / invoke Vivado; run batch Tcl |
| `config.py` | Environment-based configuration |
| `errors.py` | Typed error hierarchy |

MCP handlers never spawn subprocesses directly. There is intentionally **no**
generic `execute_tcl` / `execute_command` MCP tool.

## Testing

```bash
pytest
```

Unit tests do **not** require Vivado. Integration tests run only when Vivado is
installed and are otherwise skipped:

```bash
pytest -m integration
```

## Current limitations

- No RTL source / XDC / sim / synth / impl / bitstream tools yet
- No persistent Vivado session across MCP calls (each tool uses batch mode)
- macOS is not a supported Vivado host target
- Unusual installs should set `VIVADO_PATH` explicitly

## Roadmap

1. **Milestone 1 (complete):** Vivado discovery and version reporting
2. **Milestone 2 (complete):** Project create / open / close
3. **Milestone 3:** RTL source add/remove
4. **Milestone 4:** XDC constraint management
5. **Milestone 5:** Simulation
6. **Milestone 6:** Synthesis, implementation, bitstream
7. **Milestone 7:** Timing / utilization / message reports and debug helpers
8. **Later:** Higher-level agentic RTL/FPGA workflows

## Security

- No unrestricted shell execution through MCP
- No generic Tcl execution tool
- Paths and project names are validated before use
- Existing projects are never silently overwritten
- This project does not implement or assist with license, DRM, or activation bypasses

## Development

```bash
pip install -e ".[dev]"
pytest
python -m vivado_mcp
```

## License

MIT — see [LICENSE](LICENSE).
