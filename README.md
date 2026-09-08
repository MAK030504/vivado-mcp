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
  ProjectManager / SourceManager / SimulationManager /
  SynthesisManager / ImplementationManager
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

## Current capabilities (Milestone 6)

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
| `run_synthesis` | Run Vivado synthesis (`synth_1`) in batch mode |
| `get_utilization` | Return structured post-synthesis resource utilization |
| `run_implementation` | Run Vivado implementation / place-and-route (`impl_1`) |
| `get_implementation_status` | Return structured status for the implementation run |
| `get_implemented_utilization` | Return structured post-implementation utilization |
| `get_timing` | Prefer post-implementation timing; fall back to post-synthesis |

Supported RTL languages: **Verilog** (`.v`) and **SystemVerilog** (`.sv`).

Not implemented yet: XDC constraint management, bitstream generation, board
programming, waveform UI, RTL linting, or arbitrary Tcl execution.

**Note:** Synthesis checks whether RTL can be synthesized. Implementation
determines whether the synthesized design can be placed and routed on the
target FPGA. Prefer post-implementation timing when evaluating whether timing
is actually met.

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
git checkout cursor/vivado-mcp-milestone-6-c381
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

## Synthesis tools (Milestone 5)

### `run_synthesis`

Runs Vivado synthesis (`synth_1`) in batch mode, then writes utilization and
timing-summary reports under `{project}/.vivado_mcp/reports/`.

```text
run_synthesis(
  project_path="C:\\Users\\HP\\Documents\\VivadoProjects\\mcp_temp_synth.xpr"
)
```

Example success response:

```json
{
  "success": true,
  "status": "completed",
  "message": "Synthesis completed successfully",
  "project": "...",
  "top_module": "counter",
  "log_summary": "...",
  "errors": [],
  "warnings": []
}
```

Statuses include: `not_started`, `running`, `completed`, `failed`, `cancelled`,
`unknown`. Warnings alone do not mark synthesis as failed.

Prerequisites: project exists, design sources are present, and a top module is
set on `sources_1`.

### `get_utilization`

Returns structured resource utilization after a successful synthesis.

```text
get_utilization(
  project_path="C:\\Users\\HP\\Documents\\VivadoProjects\\mcp_temp_synth.xpr"
)
```

Example:

```json
{
  "success": true,
  "status": "available",
  "resources": {
    "lut": {"used": 12, "available": 20800, "utilization_percent": 0.06},
    "ff": {"used": 8, "available": 41600, "utilization_percent": 0.02},
    "bram": {"used": 0, "available": 50, "utilization_percent": 0.0},
    "dsp": {"used": 0, "available": 90, "utilization_percent": 0.0},
    "io": {"used": 3, "available": 106, "utilization_percent": 2.83},
    "bufg": {"used": 1, "available": 32, "utilization_percent": 3.13}
  },
  "report_path": ".../.vivado_mcp/reports/utilization.rpt"
}
```

Resource names vary by FPGA family. Missing resources are returned as `null`
instead of failing the request.

If synthesis has not been run:

```json
{
  "success": true,
  "status": "not_available",
  "reason": "Synthesis has not completed for this project. Call run_synthesis first."
}
```

### `get_timing`

Returns a post-synthesis timing summary when Vivado can produce one.

```text
get_timing(
  project_path="C:\\Users\\HP\\Documents\\VivadoProjects\\mcp_temp_synth.xpr"
)
```

Example when timing data exists:

```json
{
  "success": true,
  "status": "available",
  "timing": {
    "wns_ns": 1.42,
    "tns_ns": 0.0,
    "failing_endpoints": 0,
    "status": "met"
  }
}
```

Without timing constraints, Vivado often cannot produce meaningful post-synth
timing. In that case:

```json
{
  "success": true,
  "status": "not_available",
  "reason": "No timing constraints / timing data found after synthesis."
}
```

**Important:** Synthesis timing ≠ final implementation timing. After
implementation completes, `get_timing` prefers post-route timing.

### Example synthesis workflow

1. Create a **temporary** project (do not modify permanent `mcp_counter`)
2. `create_rtl_file` + `add_source` for design RTL
3. `run_synthesis`
4. `get_utilization`
5. `get_timing`
6. Delete the temporary project

## Implementation tools (Milestone 6)

Synthesis asks whether the RTL can be built into a netlist. Implementation
asks whether that netlist can actually be placed and routed on the chosen
FPGA. Final timing should preferably be evaluated after implementation.

### `run_implementation`

Runs Vivado place-and-route (`impl_1`) in batch mode. Requires a completed
`synth_1` run. Does **not** automatically run synthesis.

```text
run_implementation(
  project_path="C:\\Users\\HP\\Documents\\VivadoProjects\\mcp_temp_impl.xpr"
)
```

Example success response:

```json
{
  "success": true,
  "status": "completed",
  "message": "Implementation completed successfully",
  "project": "...",
  "run": "impl_1",
  "top_module": "counter"
}
```

If synthesis has not completed:

```json
{
  "success": false,
  "status": "blocked",
  "reason": "Synthesis must complete before implementation"
}
```

Statuses include: `not_started`, `running`, `completed`, `failed`, `cancelled`,
`blocked`, `timeout`, `unknown`. Warnings alone do not mark implementation as
failed. Failures are classified when possible (placement, routing, constraints,
clocking, resource exhaustion, tool failure).

### `get_implementation_status`

Queries `impl_1` status without launching a new run.

### `get_implemented_utilization`

Returns structured post-implementation resource utilization (LUT, FF, BRAM,
DSP, I/O, BUFG when present). Missing resources are `null`. Reuses the same
utilization parser as synthesis reports.

```json
{
  "success": true,
  "status": "available",
  "stage": "implementation",
  "resources": {
    "lut": {"used": 12, "available": 20800, "utilization_percent": 0.06},
    "ff": {"used": 8, "available": 41600, "utilization_percent": 0.02},
    "bram": null,
    "dsp": null,
    "io": {"used": 3, "available": 106, "utilization_percent": 2.83},
    "bufg": {"used": 1, "available": 32, "utilization_percent": 3.13}
  }
}
```

### `get_timing` (post-implementation preferred)

After a successful implementation, `get_timing` prefers post-route timing and
sets `stage` to `"implementation"`. If implementation timing is unavailable, it
falls back to Milestone 5 post-synthesis timing (`stage: "synthesis"`).

```json
{
  "success": true,
  "status": "available",
  "stage": "implementation",
  "timing": {
    "wns_ns": 1.24,
    "tns_ns": 0.0,
    "failing_endpoints": 0,
    "status": "met"
  }
}
```

Without XDC constraints, implementation may still complete, but timing often
returns:

```json
{
  "success": true,
  "status": "not_available",
  "stage": "implementation",
  "reason": "No timing constraints available"
}
```

Timing is never invented. A completed implementation is **not** reported as
timing `"met"` unless the timing report says so.

### Example implementation workflow

1. Create a **temporary** project (do not modify permanent `mcp_counter`)
2. `create_rtl_file` + `add_source` for design RTL
3. `run_synthesis` and confirm `completed`
4. `run_implementation`
5. `get_implementation_status`
6. `get_implemented_utilization`
7. `get_timing`
8. Delete the temporary project

### Known limitations (implementation)

- Designs without XDC can often implement, but meaningful timing analysis needs
  constraints
- Implementation can take much longer than synthesis; timeouts are configurable
  and return `status: timeout`
- Requires a Vivado license that includes the **Implementation** feature for the
  chosen device (WebPACK covers many Artix-7 parts including `xc7a35t`, but a
  missing/locked license or out-of-memory condition will fail place/route)
- Bitstream generation and board programming are intentionally out of scope
- No automatic timing optimization or RTL rewriting

## Security

- No unrestricted shell or Tcl execution through MCP
- Filenames are basenames only; `..` and path separators are rejected
- RTL files are written only under `rtl/`; testbenches only under `sim/`
- Existing files are never silently overwritten
- `remove_source` does not delete disk files
- `simulation_time` is validated; Tcl injection is rejected
- Synthesis/implementation/report tools only run controlled Vivado flows
  (`synth_1`, `impl_1`, `report_utilization`, `report_timing_summary`)
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

On a machine with Vivado 2018.2 installed, integration tests create temporary
projects for simulation, synthesis, and implementation workflows, then clean
up. They do not modify a permanent `mcp_counter` project.

## Current limitations

- No XDC constraint management tools yet
- No bitstream generation or board programming
- Post-synthesis timing is estimated; prefer post-implementation timing
- Timing is often unavailable without constraints (expected)
- No waveform visualization
- No automatic RTL debugging or modification
- No RTL syntax checking or linting beyond Vivado's own messages
- No persistent Vivado session across MCP calls
- macOS is not a supported Vivado host
- Utilization/timing parsers are best-effort across Vivado report formats

## Roadmap

1. **Milestone 1 — Version Detection — COMPLETE**
2. **Milestone 2 — Project Management — COMPLETE**
3. **Milestone 3 — RTL & Source Management — COMPLETE**
4. **Milestone 4 — RTL Simulation — COMPLETE** (verified on Vivado 2018.2 / Windows)
5. **Milestone 5 — Synthesis / Utilization / Timing — COMPLETE** (verified on Vivado 2018.2 / Windows)
6. **Milestone 6 — Implementation / Place-and-Route — COMPLETE** (unit/integration tests; verify on Vivado 2018.2 / Windows)
7. **Milestone 7:** XDC constraint management
8. **Milestone 8:** Bitstream generation and programming
9. **Later:** Higher-level agentic RTL/FPGA workflows

## License

MIT — see [LICENSE](LICENSE).
