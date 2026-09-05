# Cursor MCP configuration example for Vivado MCP

## Fix: "The system cannot find the path specified"

That Cursor log means the **`command` executable was not found**.
It is almost never a Vivado problem at this stage.

On Windows, do **not** rely on bare `python`. Use the full path to
`python.exe` from the environment where you installed `vivado-mcp`.

### 1. Install into a venv, then use THAT Python in Cursor

`ModuleNotFoundError: No module named 'vivado_mcp'` means Cursor launched a
Python that does not have the package. Install it, then point MCP at the
venv interpreter:

```powershell
cd C:\Users\HP\vivado-mcp
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
pip install -e .
python -c "import sys; print(sys.executable)"
python -c "import vivado_mcp; print(vivado_mcp.__file__)"
```

Both commands must succeed. Copy the printed `sys.executable` path into
Cursor MCP `command`.

### Find the real vivado.bat (important on Windows)

If `get_vivado_version` returns `vivado_not_found`, your Start Menu folder did
not resolve to an install. Discover the Target in PowerShell:

```powershell
$folder = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Xilinx Design Tools\Vivado 2018.2"
Get-ChildItem $folder -Filter *.lnk | ForEach-Object {
  (New-Object -ComObject WScript.Shell).CreateShortcut($_.FullName).TargetPath
}
Test-Path "C:\Xilinx\Vivado\2018.2\bin\vivado.bat"
```

Copy the printed `.bat` path into `VIVADO_PATH` (example below).

### 2. Cursor config (Windows)

Replace the `command` value with the exact `python.exe` path from step 1.
If you used a venv, prefer that interpreter:

```json
{
  "mcpServers": {
    "vivado": {
      "command": "C:\\Users\\HP\\vivado-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "vivado_mcp"],
      "env": {
        "VIVADO_PATH": "C:\\Xilinx\\Vivado\\2018.2\\bin\\vivado.bat",
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
& "C:\Users\HP\vivado-mcp\.venv\Scripts\python.exe" -m vivado_mcp
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
