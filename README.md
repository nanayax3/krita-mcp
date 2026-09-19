# Krita MCP Server

Let AI paint in [Krita](https://krita.org/) via the [Model Context Protocol](https://modelcontextprotocol.io/).

This bridge allows Claude (or any MCP client) to create canvases, paint strokes, draw shapes, export images, and more — all inside a running Krita instance.

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

**Layers**

| Tool | Description |
|------|-------------|
| `krita_list_layers` | List the layer tree (name, id, type, visibility, opacity, blending mode) — layer names aren't guaranteed unique, so tools that take a `name` also accept a layer's `id` |
| `krita_create_layer` | Create a paint/group/vector layer, optionally nested in a group |
| `krita_delete_layer` | Remove a layer by name |
| `krita_set_active_layer` | Make a layer the target for paint/fill/shape commands |
| `krita_set_layer_visible` | Show/hide a layer |
| `krita_set_layer_opacity` | Set layer opacity (0-100) |
| `krita_set_layer_blending_mode` | Set blending mode (multiply, screen, overlay, etc.) |
| `krita_merge_layer_down` | Merge a layer into the one beneath it |
| `krita_duplicate_layer` | Duplicate a layer |
| `krita_reorder_layer` | Move a layer up/down in the stack |
| `krita_scale_layer` / `krita_rotate_layer` / `krita_crop_layer` / `krita_shear_layer` | Resample/rotate/crop/shear a layer in place using Krita's real resampling filters |

**Selections** — constrain `stroke`/`fill`/`draw_shape` to a region until cleared

| Tool | Description |
|------|-------------|
| `krita_select_rectangle` | Select a rectangular region |
| `krita_select_all` | Select the entire canvas |
| `krita_clear_selection` | Remove the active selection |
| `krita_invert_selection` | Invert the active selection |
| `krita_grow_selection` / `krita_shrink_selection` | Expand/contract the selection |
| `krita_feather_selection` | Soften the selection edge |

**Filters**

| Tool | Description |
|------|-------------|
| `krita_list_filters` | List available filter IDs |
| `krita_apply_filter` | Apply a named filter to a layer |

**Document**

| Tool | Description |
|------|-------------|
| `krita_document_info` | Dimensions, color space, and file info |
| `krita_set_color_space` | Convert color model/depth/profile (e.g. F16/F32 for HDR) |
| `krita_list_color_profiles` | List valid profiles for a color model/depth |
| `krita_list_documents` / `krita_close_document` | Manage open documents |
| `krita_resize_canvas` / `krita_crop_canvas` | Resize or crop the canvas |
| `krita_scale_canvas` / `krita_rotate_canvas` / `krita_shear_canvas` | Resample/rotate/shear the whole canvas using Krita's real resampling filters |
| `krita_flatten_image` | Flatten all layers |
| `krita_export_layer` | Export a single layer to an image file |

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
