# Cursor MCP configuration example for Vivado MCP

Copy the `mcpServers.vivado` block from `cursor_mcp_config.json` into your
Cursor MCP settings.

## Notes

- Replace `VIVADO_PATH` with the absolute path to your Vivado executable.
- On Linux this is typically `.../Vivado/<version>/bin/vivado`.
- On Windows this is typically `...\\Vivado\\<version>\\bin\\vivado.bat`.
- If Vivado is already on your `PATH`, you may omit `VIVADO_PATH`.
- Optionally set `VIVADO_VERSION` to prefer a specific install during
  auto-detection (for example `2024.2`).
