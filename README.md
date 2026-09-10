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
  ProjectManager / SourceManager
        │
        ▼
     Vivado abstraction
        │
        ▼
     Vivado Tcl / batch CLI
        │
        ▼
   AMD/Xilinx Vivado
```

You must have your own valid Vivado installation and license. This project only
talks to whatever Vivado executable you configure.

## Current capabilities (Milestone 3)

| Tool | Description |
|------|-------------|
| `get_vivado_version` | Locate Vivado and return structured version information |
| `create_project` | Create a new Vivado project for a given FPGA part |
| `open_project` | Open/verify an existing `.xpr` project in batch mode |
| `close_project` | Close a project cleanly via batch-mode Tcl |
| `create_rtl_file` | Create a `.v` / `.sv` file under the project's `rtl/` folder |
| `add_source` | Add an existing RTL file to the Vivado project |
| `remove_source` | Remove a source from the project (does **not** delete the file) |
| `list_sources` | List design sources with path/type/library |

Supported RTL languages: **Verilog** (`.v`) and **SystemVerilog** (`.sv`).

Not implemented yet: XDC constraints, simulation, synthesis, implementation,
bitstream generation, timing/utilization reports, RTL linting, or arbitrary
Tcl execution.

## Requirements

- Python 3.11+
- An MCP-compatible client (for example Cursor)
- A local AMD/Xilinx Vivado installation (**Windows** or **Linux**)
- Verified with **Vivado 2018.2** on Windows

## Installation

### Windows (PowerShell)

```powershell
git clone https://github.com/MAK030504/vivado-mcp.git
cd C:\Users\HP\vivado-mcp
git fetch
git checkout cursor/vivado-mcp-milestone-3-c381
.\.venv\Scripts\activate
pip install -e .
python -c "import vivado_mcp; print(vivado_mcp.__version__)"
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

| Variable | Purpose |
|----------|---------|
| `VIVADO_PATH` | Absolute path to `vivado.bat` / `vivado` |
| `VIVADO_VERSION` | Optional preferred version (e.g. `2018.2`) |
| `VIVADO_WORKSPACE` | Optional default workspace (reserved) |

Cursor MCP config example:

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

Keep this MCP config the same across milestones unless the Python or Vivado
path changes. After pulling new code, run `pip install -e .` and restart Cursor.

## Tool examples

### `create_rtl_file`

Creates `{project_dir}/rtl/{filename}` and does **not** register it in Vivado
yet.

```text
create_rtl_file(
  project_path="C:\\Users\\HP\\Documents\\VivadoProjects\\mcp_counter.xpr",
  filename="counter.v",
  language="verilog",
  code="module counter(input clk, output reg [3:0] q); ..."
)
```

### `add_source`

```text
add_source(
  project_path="C:\\Users\\HP\\Documents\\VivadoProjects\\mcp_counter.xpr",
  source_path="C:\\Users\\HP\\Documents\\VivadoProjects\\rtl\\counter.v"
)
```

### `list_sources`

```json
{
  "success": true,
  "sources": [
    {
      "path": ".../rtl/counter.v",
      "type": "verilog",
      "library": "xil_defaultlib"
    }
  ]
}
```

### `remove_source`

Removes the file from the project file set only. The physical `.v` / `.sv`
file remains on disk.

## Security

- No unrestricted shell or Tcl execution through MCP
- Filenames are basenames only; `..` and path separators are rejected
- RTL files are written only under the project `rtl/` directory
- Existing RTL files are never silently overwritten
- `remove_source` does not delete disk files
- This project does not assist with license/DRM bypasses

## Testing

```bash
pytest
```

Unit tests do not require Vivado. Integration tests skip automatically when
Vivado is unavailable:

```bash
pytest -m integration
```

## Current limitations

- No XDC / sim / synth / impl / bitstream tools yet
- No RTL syntax checking or linting
- No persistent Vivado session across MCP calls
- macOS is not a supported Vivado host

## Roadmap

1. **Milestone 1 (complete):** Vivado discovery and version reporting
2. **Milestone 2 (complete):** Project create / open / close
3. **Milestone 3 (complete):** RTL source create / add / remove / list
4. **Milestone 4:** XDC constraint management
5. **Milestone 5:** Simulation
6. **Milestone 6:** Synthesis, implementation, bitstream
7. **Milestone 7:** Timing / utilization / message reports
8. **Later:** Higher-level agentic RTL/FPGA workflows

## License

MIT — see [LICENSE](LICENSE).
