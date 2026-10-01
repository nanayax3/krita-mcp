# Krita MCP Server Qt6 / PyQt6 Compatibility

Let AI paint in [Krita](https://krita.org/) via the [Model Context Protocol](https://modelcontextprotocol.io/).

This bridge allows Claude (or any MCP client) to create canvases, paint strokes, draw shapes, export images, and more — all inside a running Krita instance.

## About This Fork

Based on [nanayax3/krita-mcp](https://github.com/nanayax3/krita-mcp), with a Qt compatibility update prepared by [Badee Sindi](https://github.com/badeesindi).

- Adds PyQt6 imports for Krita 6, with a PyQt5 fallback for Krita 5.
- Removes unused Qt imports from the plugin.
- Documents Windows interpreter selection, missing dependencies, and connection checks.
- Preserves the upstream painting implementation, MCP tools, 120-second export/save timeouts, and MIT license.

The maintainer reported successful connection on Windows after applying this patch and installing the server dependencies on October 1, 2026. Python syntax and simulated import/registration checks passed for both Qt import branches. This is not a claim that every painting tool or both Krita major versions were tested in the real application.

## How It Works

Two components:

1. **Krita Plugin** (`krita-plugin/`) — A Python plugin that runs inside Krita, exposing an HTTP server on `localhost:5678`. It receives paint commands and executes them on Krita's main thread via a command queue.

2. **MCP Server** (`server.py`) — A [FastMCP](https://github.com/jlowin/fastmcp) server that exposes painting tools to any MCP client. It translates MCP tool calls into HTTP requests to the Krita plugin.

```
MCP Client (Claude, etc.)  ←→  MCP Server (server.py)  ←→  Krita Plugin (HTTP on :5678)  ←→  Krita
```

## Setup

### 1. Install the Krita Plugin

Copy the plugin files to your Krita plugins directory:

| OS | Path |
|----|------|
| Windows | `%APPDATA%\krita\pykrita\` |
| Linux | `~/.local/share/krita/pykrita/` |
| macOS | `~/Library/Application Support/krita/pykrita/` |

Copy both:
- `krita-plugin/kritamcp/` (the folder with `__init__.py`)
- `krita-plugin/kritamcp.desktop`

Then in Krita: **Settings → Configure Krita → Python Plugin Manager → Enable "Krita MCP Bridge"** and restart Krita.

### 2. Install the MCP Server

```bash
pip install fastmcp httpx
```

Or with a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 3. Configure Your MCP Client

Add to your MCP client config (e.g., Claude Desktop's `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "krita": {
      "command": "python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

If using a virtual environment:
```json
{
  "mcpServers": {
    "krita": {
      "command": "/path/to/.venv/Scripts/python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

### Windows: Use the Same Python for Installation and Claude

Krita's embedded Python runs the plugin. A separate Python interpreter runs `server.py`; install `fastmcp` and `httpx` into that interpreter, not into Krita's embedded Python.

For an isolated installation, open PowerShell in the downloaded repository folder:

```powershell
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" -c "from fastmcp import FastMCP; import httpx; print('READY')"
```

Use absolute paths in Claude's configuration. For example, if the repository is at `C:\Tools\krita-mcp`:

```json
{
  "mcpServers": {
    "krita": {
      "command": "C:\\Tools\\krita-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Tools\\krita-mcp\\server.py"]
    }
  }
}
```

Replace these example paths with your actual installation paths. Merge the `krita` entry into your existing configuration without removing other servers or preferences. `server.py` is at the repository root; the `kritamcp` plugin folder contains `__init__.py`, not `server.py`. If you choose to store the server elsewhere, point `args` at its actual location.

Fully quit and reopen Claude after changing the configuration.

### Verify the Connection

1. Restart Krita after copying/enabling the plugin.
2. Open `http://localhost:5678/health` in your browser. Expected response: `{"status": "ok", "plugin": "kritamcp"}`. This checks the plugin's HTTP listener, not every painting operation.
3. Start Claude and ask it to run `krita_health`.
4. Ask it to create a small test canvas to verify command execution.

### Troubleshooting

| Symptom | Cause or next check |
|---------|---------------------|
| Plugin is grayed out | Hover over its name in Python Plugin Manager to see the import error. |
| `This version of Krita is not compatible with PyQt5!` | Replace the plugin's `__init__.py` with this fork's version, then restart Krita. Do not install PyQt5 into a Qt6-based Krita. |
| `can't open file ... server.py` | Correct `args` to the actual absolute path of `server.py`. |
| `No module named 'fastmcp'` or `'httpx'` | Run `-m pip install -r requirements.txt` using the exact Python executable configured in `command`. |
| Claude reports `Server disconnected` | Inspect its MCP logs for the underlying exception. This message alone does not identify a Krita plugin problem. |
| Health URL is unreachable | Check that Krita is running, the plugin loaded, and port 5678 is available. |

Do not publish your personal `claude_desktop_config.json`, logs, or generated `.pyc` files. Use the generic example above for shared setup instructions.

## Available Tools

| Tool | Description |
|------|-------------|
| `krita_health` | Check if Krita is running with the plugin active |
| `krita_new_canvas` | Create a new canvas (width, height, background color) |
| `krita_set_color` | Set foreground paint color (hex) |
| `krita_set_brush` | Set brush preset, size, and opacity |
| `krita_stroke` | Paint a stroke through a list of [x, y] points |
| `krita_fill` | Fill a circular area at a point |
| `krita_draw_shape` | Draw rectangle, ellipse, or line |
| `krita_get_canvas` | Export canvas to PNG (for AI to see progress) |
| `krita_save` | Save canvas to a specific file path |
| `krita_undo` / `krita_redo` | Undo/redo actions |
| `krita_clear` | Clear canvas to a solid color |
| `krita_get_color_at` | Eyedropper — sample color at a pixel |
| `krita_list_brushes` | List available brush presets |
| `krita_open_file` | Open an existing .kra, .png, .jpg, etc. |

## The Export Timeout Fix

**This is the main reason this repo exists.**

By default, HTTP requests and command queue operations time out after ~30 seconds. Canvas export (`get_canvas`) and file save (`save`) operations can easily exceed this on larger canvases, causing silent failures or timeout errors.

The fix is applied in two places:

**MCP Server (`server.py`)** — Extended timeout for export/save commands:
```python
# In krita_get_canvas and krita_save:
result = send_command("get_canvas", {"filename": filename}, timeout=120.0)
result = send_command("save", {"path": path}, timeout=120.0)
```

**Krita Plugin (`__init__.py`)** — Matching timeout in the command queue:
```python
def get_result(self, command_id, timeout=120):
    """Wait for result with timeout."""
    for _ in range(int(timeout * 10)):  # Check every 100ms
        ...
```

**Both sides must match.** If only the MCP server timeout is increased, the plugin's command queue will still time out at 30s. If only the plugin timeout is increased, the HTTP request from the MCP server will time out first.

## Configuration

| Setting | Default | How to Change |
|---------|---------|---------------|
| Plugin HTTP port | `5678` | Edit `SERVER_PORT` in plugin `__init__.py` |
| MCP server URL | `http://localhost:5678` | Set `KRITA_URL` env var |
| Canvas output dir | `~/krita-mcp-output` | Edit `CANVAS_OUTPUT_DIR` in plugin `__init__.py` |

## Painting Approach

The plugin paints using **direct pixel manipulation** (not Krita's native brush engine for strokes). This means:

- Strokes use a custom soft-circle renderer with configurable hardness
- Alpha blending is done manually in BGRA pixel format
- Shapes (rectangle, ellipse, line) are rasterized directly
- This approach is reliable and doesn't depend on Krita's internal brush state

The `set_brush` tool does set Krita's brush preset (for potential future use), but `stroke` currently uses its own pixel-level rendering.

## License

MIT
