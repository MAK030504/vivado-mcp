# Cursor MCP configuration example for Vivado MCP

Copy the `mcpServers.vivado` block from `cursor_mcp_config.json` into your
Cursor MCP settings.

## Windows (Vivado 2018.2)

You can set `VIVADO_PATH` to either:

1. Your Start Menu folder (accepted and resolved automatically when possible):

```text
C:\Users\HP\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Xilinx Design Tools\Vivado 2018.2
```

2. Or the real launcher (most reliable):

```text
C:\Xilinx\Vivado\2018.2\bin\vivado.bat
```

Vivado MCP treats the Start Menu path as a version hint (`2018.2`) and looks
for `vivado.bat` under normal Xilinx install roots.

If automatic resolution fails, open the Start Menu entry → right-click →
More → Open file location → Properties → copy **Target**, and set that as
`VIVADO_PATH`.

## Notes

- On Linux this is typically `.../Vivado/2018.2/bin/vivado`.
- If Vivado is already on your `PATH`, you may omit `VIVADO_PATH`.
- Optionally set `VIVADO_VERSION` (for example `2018.2`) to prefer that
  install when multiple versions are present.
