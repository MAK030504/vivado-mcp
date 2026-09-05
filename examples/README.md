# Cursor MCP configuration example for Vivado MCP

Copy the `mcpServers.vivado` block from `cursor_mcp_config.json` into your
Cursor MCP settings.

## Windows (Vivado 2018.2)

Use the **real launcher**, not the Start Menu folder:

```text
C:\Users\...\Start Menu\Programs\Xilinx Design Tools\Vivado 2018.2   ← wrong
C:\Xilinx\Vivado\2018.2\bin\vivado.bat                               ← correct
```

How to confirm the Target path from the Start Menu entry:

1. Open the Start Menu → Xilinx Design Tools → Vivado 2018.2
2. Right-click → More → Open file location
3. Right-click the Vivado shortcut → Properties
4. Copy the **Target** value (usually `...\Vivado\2018.2\bin\vivado.bat`)
5. Set that as `VIVADO_PATH`

## Notes

- On Linux this is typically `.../Vivado/2018.2/bin/vivado`.
- If Vivado is already on your `PATH`, you may omit `VIVADO_PATH`.
- Optionally set `VIVADO_VERSION` (for example `2018.2`) to prefer that
  install when multiple versions are present.
