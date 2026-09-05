# Cursor MCP configuration example for Vivado MCP

## Fix: "The system cannot find the path specified"

That Cursor log means the **`command` executable was not found**.
It is almost never a Vivado problem at this stage.

On Windows, do **not** rely on bare `python`. Use the full path to
`python.exe` from the environment where you installed `vivado-mcp`.

### 1. Find your Python

In PowerShell:

```powershell
where.exe python
python -c "import sys; print(sys.executable)"
python -c "import vivado_mcp; print(vivado_mcp.__file__)"
```

If the last command fails, install the package first:

```powershell
cd C:\path\to\vivado-mcp
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
python -c "import vivado_mcp; print('ok', vivado_mcp.__file__)"
```

### 2. Cursor config (Windows)

Replace the `command` value with the exact `python.exe` path from step 1.
If you used a venv, prefer that interpreter:

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

Notes:

- Use `\\` in JSON paths.
- `command` must point to an existing `.exe` file.
- `VIVADO_PATH` can be your Start Menu Vivado 2018.2 folder; the server
  resolves it to `vivado.bat` when possible.
- After changing MCP settings, fully restart Cursor (or reload MCP servers).

### 3. Smoke-test outside Cursor

```powershell
& "C:\Users\HP\path\to\vivado-mcp\.venv\Scripts\python.exe" -m vivado_mcp
```

It should start and wait (stdio MCP). Ctrl+C to stop.
If Windows says path not found here too, fix `command` before retrying Cursor.

## Linux note

```json
{
  "mcpServers": {
    "vivado": {
      "command": "python3",
      "args": ["-m", "vivado_mcp"],
      "env": {
        "VIVADO_PATH": "/tools/Xilinx/Vivado/2018.2/bin/vivado",
        "VIVADO_VERSION": "2018.2"
      }
    }
  }
}
```
