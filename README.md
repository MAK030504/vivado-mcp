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
  ProjectManager / SourceManager / SimulationManager
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

## Current capabilities (Milestone 4)

| Tool | Description |
|------|-------------|
| `get_vivado_version` | Locate Vivado and return structured version information |
| `create_project` | Create a new Vivado project for a given FPGA part |
| `open_project` | Open/verify an existing `.xpr` project in batch mode |
| `close_project` | Close a project cleanly via batch-mode Tcl |
| `create_rtl_file` | Create a `.v` / `.sv` file under the project's `rtl/` folder |
| `add_source` | Add an existing RTL file to `sources_1` or `sim_1` |
| `remove_source` | Remove a source from the project (does **not** delete the file) |
| `list_sources` | List design sources with path/type/library |
| `create_testbench` | Create a `.v` / `.sv` testbench under the project's `sim/` folder |
| `run_simulation` | Run RTL behavioral simulation with XSim in batch mode |
| `get_simulation_status` | Return structured status for the most recent simulation |

Supported RTL languages: **Verilog** (`.v`) and **SystemVerilog** (`.sv`).

Not implemented yet: XDC constraints, synthesis, implementation, bitstream
generation, timing/utilization reports, waveform UI, RTL linting, or arbitrary
Tcl execution.

## Requirements

- Python 3.11+
- An MCP-compatible client (for example Cursor)
- A local AMD/Xilinx Vivado installation (**Windows** or **Linux**)
- Verified target: **Vivado 2018.2** on Windows

## Installation

### Windows (PowerShell)

```powershell
git clone https://github.com/mak030504/vivado-mcp.git
cd C:\Users\HP\vivado-mcp
git fetch
git checkout cursor/vivado-mcp-milestone-4-c381
.\.venv\Scripts\activate
pip install -e .
python -c "import vivado_mcp; print(vivado_mcp.__version__)"
```

### Linux / macOS

```bash
git clone https://github.com/mak030504/vivado-mcp.git
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

## Simulation tools (Milestone 4)

### `create_testbench`

Creates `{project_dir}/sim/{filename}` and does **not** register it in Vivado.
Call `add_source(..., fileset="sim_1")` next. Refuses to overwrite existing files.
Does not execute the supplied code.

```text
create_testbench(
  project_path="C:\\Users\\HP\\Documents\\VivadoProjects\\mcp_counter.xpr",
  filename="counter_tb.v",
  language="verilog",
  code="`timescale 1ns/1ps\nmodule counter_tb; ..."
)
```

Example response:

```json
{
  "success": true,
  "file": {
    "path": ".../sim/counter_tb.v",
    "language": "verilog",
    "type": "testbench"
  }
}
```

### `add_source` with simulation fileset

Design RTL stays in `sources_1`. Testbenches must go into `sim_1`:

```text
add_source(
  project_path="C:\\Users\\HP\\Documents\\VivadoProjects\\mcp_counter.xpr",
  source_path="C:\\Users\\HP\\Documents\\VivadoProjects\\sim\\counter_tb.v",
  fileset="sim_1"
)
```

### `run_simulation`

Runs Vivado XSim behavioral simulation in batch mode (no GUI).

```text
run_simulation(
  project_path="C:\\Users\\HP\\Documents\\VivadoProjects\\mcp_counter.xpr",
  top_module="counter_tb",
  simulation_time="100ns"
)
```

`simulation_time` accepts values such as `10ns`, `100ns`, `1us`, `1ms`. Arbitrary
Tcl expressions are rejected.

Example success response:

```json
{
  "success": true,
  "status": "completed",
  "top_module": "counter_tb",
  "simulation_time": "100ns",
  "errors": 0,
  "warnings": 0,
  "output": "...",
  "vivado_version": "2018.2"
}
```

Failure responses distinguish useful states when possible:

| `status` | Meaning |
|----------|---------|
| `compile_error` | HDL / testbench compile failure |
| `elaborate_error` | Elaboration failure |
| `runtime_error` | Simulation runtime / fatal error |
| `assertion_failed` | Assertion / `$fatal` / `$error` failure |
| `no_sources` | No files in `sim_1` |
| `failed` | Generic / unclassified failure |
| `completed` / `passed` | Successful run |

### `get_simulation_status`

Returns structured info about the most recent simulation for a project. If none
has been run, returns `status: "not_run"` (not an exception).

```text
get_simulation_status(
  project_path="C:\\Users\\HP\\Documents\\VivadoProjects\\mcp_counter.xpr"
)
```

### Example counter workflow

1. `create_project` (or reuse a temporary project — do not overwrite permanent ones in tests)
2. `create_rtl_file` → counter RTL under `rtl/`
3. `add_source` → `sources_1`
4. `create_testbench` → counter testbench under `sim/`
5. `add_source(..., fileset="sim_1")`
6. `run_simulation(top_module="counter_tb", simulation_time="100ns")`
7. `get_simulation_status`

A good testbench should generate a clock, assert/release reset, run for several
cycles, print deterministic `$display` output, then `$finish`.

## Security

- No unrestricted shell or Tcl execution through MCP
- Filenames are basenames only; `..` and path separators are rejected
- RTL files are written only under `rtl/`; testbenches only under `sim/`
- Existing files are never silently overwritten
- `remove_source` does not delete disk files
- `simulation_time` is validated; Tcl injection is rejected
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

On a machine with Vivado 2018.2 installed, the simulation integration test
creates a temporary project, builds a counter + testbench, runs 100ns of
simulation, checks output, then cleans up. It does not modify a permanent
`mcp_counter` project.

## Current limitations

- No XDC / synth / impl / bitstream tools yet
- No waveform visualization
- No automatic RTL debugging or modification
- No RTL syntax checking or linting beyond Vivado's own messages
- No persistent Vivado session across MCP calls
- macOS is not a supported Vivado host
- Simulation status classification is best-effort from Vivado logs

## Roadmap

1. **Milestone 1 — Version Detection — COMPLETE**
2. **Milestone 2 — Project Management — COMPLETE**
3. **Milestone 3 — RTL & Source Management — COMPLETE**
4. **Milestone 4 — RTL Simulation — IN PROGRESS** (implementation + unit tests done; confirm with real Vivado 2018.2)
5. **Milestone 5:** XDC constraint management
6. **Milestone 6:** Synthesis, implementation, bitstream
7. **Milestone 7:** Timing / utilization / message reports
8. **Later:** Higher-level agentic RTL/FPGA workflows

## License

MIT — see [LICENSE](LICENSE).
