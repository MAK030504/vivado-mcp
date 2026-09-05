# Cursor MCP configuration example for Vivado MCP

Copy the `mcpServers.vivado` block from `cursor_mcp_config.json` into your
Cursor MCP settings.

## Notes

- Replace `VIVADO_PATH` with the absolute path to your Vivado executable.
- On Linux this is typically `.../Vivado/2018.2/bin/vivado` (adjust the
  version directory to match your install).
- On Windows this is typically `...\\Vivado\\2018.2\\bin\\vivado.bat`.
- If Vivado is already on your `PATH`, you may omit `VIVADO_PATH`.
- Optionally set `VIVADO_VERSION` (for example `2018.2`) to prefer that
  install when multiple versions are present.
