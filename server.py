"""
Krita MCP Server
Bridge between Claude (or any MCP client) and Krita painting application.

Uses FastMCP to expose Krita painting tools over the Model Context Protocol,
communicating with a Krita plugin via HTTP.
"""

from fastmcp import FastMCP
import httpx
import os
from typing import Optional

# Configuration
KRITA_URL = os.environ.get("KRITA_URL", "http://localhost:5678")

mcp = FastMCP("krita-mcp")


def send_command(action: str, params: dict = None, timeout: float = 30.0) -> dict:
    """Send command to Krita plugin and return result."""
    if params is None:
        params = {}

    try:
        response = httpx.post(
            KRITA_URL,
            json={"action": action, "params": params},
            timeout=timeout
        )
        return response.json()
    except httpx.ConnectError:
        return {"error": "Cannot connect to Krita. Is Krita running with the MCP plugin enabled?"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def krita_health() -> str:
    """Check if Krita is running and the MCP plugin is active."""
    try:
        response = httpx.get(f"{KRITA_URL}/health", timeout=5.0)
        data = response.json()
        return f"Krita is running. Plugin: {data.get('plugin', 'unknown')}"
    except:
        return "Cannot connect to Krita. Make sure Krita is running with the MCP plugin enabled."


@mcp.tool()
def krita_new_canvas(
    width: int = 800,
    height: int = 600,
    name: str = "New Canvas",
    background: str = "#1a1a2e"
) -> str:
    """
    Create a new canvas in Krita.

    Args:
        width: Canvas width in pixels (default 800)
        height: Canvas height in pixels (default 600)
        name: Document name
        background: Background color as hex (default dark blue)
    """
    result = send_command("new_canvas", {
        "width": width,
        "height": height,
        "name": name,
        "background": background
    })

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Created canvas: {width}x{height}, background: {background}"


@mcp.tool()
def krita_set_color(color: str) -> str:
    """
    Set the foreground (paint) color.

    Args:
        color: Hex color code (e.g., "#ff6b6b", "#b8a9c9")
    """
    result = send_command("set_color", {"color": color})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Color set to {color}"


@mcp.tool()
def krita_set_brush(
    preset: Optional[str] = None,
    size: Optional[int] = None,
    opacity: Optional[float] = None
) -> str:
    """
    Set brush preset and properties.

    Args:
        preset: Brush preset name (partial match, e.g., "Basic", "Soft", "Airbrush")
        size: Brush size in pixels
        opacity: Brush opacity (0.0 to 1.0)
    """
    params = {}
    if preset:
        params["preset"] = preset
    if size:
        params["size"] = size
    if opacity is not None:
        params["opacity"] = opacity

    result = send_command("set_brush", params)

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Brush set: preset={preset}, size={size}, opacity={opacity}"


@mcp.tool()
def krita_stroke(points: list[list[int]], pressure: float = 1.0) -> str:
    """
    Paint a stroke through a series of points.

    Args:
        points: List of [x, y] coordinate pairs, e.g., [[100, 100], [150, 120], [200, 150]]
        pressure: Brush pressure (0.0 to 1.0, affects stroke thickness/opacity)
    """
    if len(points) < 2:
        return "Error: Need at least 2 points for a stroke"

    result = send_command("stroke", {
        "points": points,
        "pressure": pressure
    })

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Stroke painted with {len(points)} points"


@mcp.tool()
def krita_fill(x: int, y: int, radius: int = 50) -> str:
    """
    Fill an area with current color (paints a filled circle at the point).

    Args:
        x: X coordinate
        y: Y coordinate
        radius: Fill radius in pixels
    """
    result = send_command("fill", {"x": x, "y": y, "radius": radius})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Filled at ({x}, {y}) with radius {radius}"


@mcp.tool()
def krita_draw_shape(
    shape: str,
    x: int,
    y: int,
    width: int = 100,
    height: int = 100,
    fill: bool = True,
    stroke: bool = False,
    x2: Optional[int] = None,
    y2: Optional[int] = None
) -> str:
    """
    Draw a shape on the canvas.

    Args:
        shape: Type of shape - "rectangle", "ellipse", or "line"
        x: X coordinate (top-left for shapes, start point for lines)
        y: Y coordinate (top-left for shapes, start point for lines)
        width: Width of shape (ignored for lines if x2/y2 provided)
        height: Height of shape (ignored for lines if x2/y2 provided)
        fill: Whether to fill the shape
        stroke: Whether to draw outline
        x2: End X for lines (optional)
        y2: End Y for lines (optional)
    """
    params = {
        "shape": shape,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "fill": fill,
        "stroke": stroke
    }
    if x2 is not None:
        params["x2"] = x2
    if y2 is not None:
        params["y2"] = y2

    result = send_command("draw_shape", params)

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Drew {shape} at ({x}, {y})"


@mcp.tool()
def krita_get_canvas(filename: str = "canvas.png") -> str:
    """
    Export current canvas to a PNG file and return the path.
    Use this to see your painting progress.

    Args:
        filename: Output filename (saved to configured output directory)
    """
    # Extended timeout — canvas export can take a while on large canvases
    result = send_command("get_canvas", {"filename": filename}, timeout=120.0)

    if "error" in result:
        return f"Error: {result['error']}"

    path = result.get("path", "")
    return f"Canvas saved to: {path}"


@mcp.tool()
def krita_undo() -> str:
    """Undo the last action."""
    result = send_command("undo", {})

    if "error" in result:
        return f"Error: {result['error']}"
    return "Undone"


@mcp.tool()
def krita_redo() -> str:
    """Redo the last undone action."""
    result = send_command("redo", {})

    if "error" in result:
        return f"Error: {result['error']}"
    return "Redone"


@mcp.tool()
def krita_clear(color: str = "#1a1a2e") -> str:
    """
    Clear the canvas to a solid color.

    Args:
        color: Color to fill canvas with (default dark blue)
    """
    result = send_command("clear", {"color": color})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Canvas cleared to {color}"


@mcp.tool()
def krita_save(path: str) -> str:
    """
    Save the current canvas to a specific file path.

    Args:
        path: Full file path to save to (e.g., "C:/art/my_painting.png")
    """
    # Extended timeout — saving large files can take a while
    result = send_command("save", {"path": path}, timeout=120.0)

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Saved to {path}"


@mcp.tool()
def krita_get_color_at(x: int, y: int) -> str:
    """
    Sample the color at a specific pixel (eyedropper).

    Args:
        x: X coordinate
        y: Y coordinate
    """
    result = send_command("get_color_at", {"x": x, "y": y})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Color at ({x}, {y}): {result.get('color', 'unknown')} (R:{result.get('r')}, G:{result.get('g')}, B:{result.get('b')})"


@mcp.tool()
def krita_list_brushes(filter: str = "", limit: int = 20) -> str:
    """
    List available brush presets.

    Args:
        filter: Filter brushes by name (partial match)
        limit: Maximum number to return
    """
    result = send_command("list_brushes", {"filter": filter, "limit": limit})

    if "error" in result:
        return f"Error: {result['error']}"

    brushes = result.get("brushes", [])
    if not brushes:
        return "No brushes found matching filter"

    return f"Available brushes ({len(brushes)}):\n" + "\n".join(f"  - {b}" for b in brushes)


@mcp.tool()
def krita_open_file(path: str) -> str:
    """
    Open an existing file in Krita (.kra, .png, .jpg, etc).

    Args:
        path: Full file path to open (e.g., "C:/art/my_painting.kra")
    """
    result = send_command("open_file", {"path": path}, timeout=30.0)

    if "error" in result:
        return f"Error: {result['error']}"

    return f"Opened: {result.get('name', 'unknown')} ({result.get('width')}x{result.get('height')})"


# --- Layers ---

@mcp.tool()
def krita_list_layers() -> str:
    """
    List the layer tree of the active document (name, id, type, visibility, opacity, blending
    mode). Layer names are NOT guaranteed unique — if two layers share a name, pass the id shown
    here (not the name) to any other tool's "name" parameter (create_layer, delete_layer,
    set_active_layer, etc. all accept either) to target the exact one you mean.
    """
    result = send_command("list_layers", {})

    if "error" in result:
        return f"Error: {result['error']}"

    def format_layers(layers, indent=0):
        lines = []
        for layer in layers:
            prefix = "  " * indent + "- "
            vis = "" if layer["visible"] else " (hidden)"
            lines.append(
                f"{prefix}{layer['name']} (id={layer['id']}) [{layer['type']}] "
                f"opacity={layer['opacity']}/255 blend={layer['blendingMode']}{vis}"
            )
            lines.extend(format_layers(layer["children"], indent + 1))
        return lines

    lines = format_layers(result.get("layers", []))
    if not lines:
        return "No layers"
    return "\n".join(lines)


@mcp.tool()
def krita_find_nodes(
    name: str = "",
    type: Optional[str] = None,
    color_label: int = 0,
    recursive: bool = True,
    partial_match: bool = False,
    under: Optional[str] = None,
) -> str:
    """
    Search the layer tree for nodes matching name/type/color-label criteria — for pulling out
    specific layers/masks in a large document without parsing list_layers' full tree dump.

    Args:
        name: Name to match (empty = match any name)
        type: Node type to filter by, e.g. "paintlayer", "vectorlayer", "grouplayer",
            "filllayer", "clonelayer", "filelayer", "filtermask", "transparencymask",
            "selectionmask", "colorizemask", "transformmask" (omit for any type)
        color_label: Krita's layer color-label index to filter by (omit/0 for any)
        recursive: Search nested groups too (default True)
        partial_match: Substring match instead of exact name match
        under: Restrict the search to this layer/group's subtree (name or id) — default: the
            whole document
    """
    params = {
        "name": name, "recursive": recursive, "partial_match": partial_match,
        "color_label": color_label,
    }
    if type:
        params["type"] = type
    if under:
        params["under"] = under
    result = send_command("find_nodes", params)

    if "error" in result:
        return f"Error: {result['error']}"

    def format_layers(layers, indent=0):
        lines = []
        for layer in layers:
            prefix = "  " * indent + "- "
            vis = "" if layer["visible"] else " (hidden)"
            lines.append(
                f"{prefix}{layer['name']} (id={layer['id']}) [{layer['type']}] "
                f"opacity={layer['opacity']}/255 blend={layer['blendingMode']}{vis}"
            )
            lines.extend(format_layers(layer["children"], indent + 1))
        return lines

    lines = format_layers(result.get("nodes", []))
    if not lines:
        return "No matching nodes"
    return "\n".join(lines)


@mcp.tool()
def krita_create_layer(name: str = "New Layer", type: str = "paint", parent: Optional[str] = None) -> str:
    """
    Create a new layer.

    Args:
        name: Layer name (not required to be unique — the returned id is the reliable way to
            reference this exact layer later, e.g. in parent, or any other tool's "name" param)
        type: "paint", "group", or "vector"
        parent: Name (or id) of an existing group layer to nest inside (default: top level)
    """
    params = {"name": name, "type": type}
    if parent:
        params["parent"] = parent
    result = send_command("create_layer", params)

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Created layer '{result.get('name')}' (id={result.get('id')}) ({result.get('type')})"


@mcp.tool()
def krita_delete_layer(name: str) -> str:
    """Delete a layer by name, or by id (see list_layers) if the name might be ambiguous."""
    result = send_command("delete_layer", {"name": name})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Deleted layer '{name}'"


@mcp.tool()
def krita_set_active_layer(name: str) -> str:
    """Make a layer active (by name or id — see list_layers) — subsequent stroke/fill/draw_shape/
    clear commands target it."""
    result = send_command("set_active_layer", {"name": name})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Active layer set to '{name}'"


@mcp.tool()
def krita_set_layer_visible(name: str, visible: bool = True) -> str:
    """Show or hide a layer."""
    result = send_command("set_layer_visible", {"name": name, "visible": visible})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Layer '{name}' visibility set to {visible}"


@mcp.tool()
def krita_set_layer_opacity(name: str, opacity: float) -> str:
    """
    Set a layer's opacity.

    Args:
        name: Layer name
        opacity: 0-100
    """
    result = send_command("set_layer_opacity", {"name": name, "opacity": opacity})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Layer '{name}' opacity set to {opacity}"


@mcp.tool()
def krita_set_layer_blending_mode(name: str, mode: str) -> str:
    """
    Set a layer's blending mode.

    Args:
        name: Layer name
        mode: e.g. "normal", "multiply", "screen", "overlay", "addition", "darken", "lighten"
    """
    result = send_command("set_layer_blending_mode", {"name": name, "mode": mode})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Layer '{name}' blending mode set to {mode}"


@mcp.tool()
def krita_merge_layer_down(name: str) -> str:
    """Merge a layer with the visible layer beneath it."""
    result = send_command("merge_layer_down", {"name": name})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Merged into '{result.get('merged_name')}'"


@mcp.tool()
def krita_duplicate_layer(name: str) -> str:
    """Duplicate a layer (by name or id — see list_layers), inserting the copy directly above the
    original."""
    result = send_command("duplicate_layer", {"name": name})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Duplicated as '{result.get('name')}' (id={result.get('id')})"


@mcp.tool()
def krita_reorder_layer(name: str, direction: str) -> str:
    """
    Move a layer one step up or down in its parent's stacking order.

    Args:
        name: Layer name
        direction: "up" or "down"
    """
    result = send_command("reorder_layer", {"name": name, "direction": direction})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Moved '{name}' {direction}"


# --- Selections ---

@mcp.tool()
def krita_select_rectangle(x: int, y: int, width: int, height: int) -> str:
    """Set the active selection to a rectangle. Fill/stroke/draw_shape are clipped to it until cleared."""
    result = send_command("select_rectangle", {"x": x, "y": y, "width": width, "height": height})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Selected rectangle at ({x}, {y}), {width}x{height}"


@mcp.tool()
def krita_select_all() -> str:
    """Select the entire canvas."""
    result = send_command("select_all", {})

    if "error" in result:
        return f"Error: {result['error']}"
    return "Selected entire canvas"


@mcp.tool()
def krita_clear_selection() -> str:
    """Remove the active selection."""
    result = send_command("clear_selection", {})

    if "error" in result:
        return f"Error: {result['error']}"
    return "Selection cleared"


@mcp.tool()
def krita_invert_selection() -> str:
    """Invert the active selection."""
    result = send_command("invert_selection", {})

    if "error" in result:
        return f"Error: {result['error']}"
    return "Selection inverted"


@mcp.tool()
def krita_grow_selection(radius: int = 5) -> str:
    """Grow the active selection outward by radius pixels."""
    result = send_command("grow_selection", {"radius": radius})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Selection grown by {radius}px"


@mcp.tool()
def krita_shrink_selection(radius: int = 5) -> str:
    """Shrink the active selection inward by radius pixels."""
    result = send_command("shrink_selection", {"radius": radius})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Selection shrunk by {radius}px"


@mcp.tool()
def krita_feather_selection(radius: int = 5) -> str:
    """Feather (soften the edge of) the active selection."""
    result = send_command("feather_selection", {"radius": radius})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Selection feathered by {radius}px"


# --- Filters ---

@mcp.tool()
def krita_list_filters() -> str:
    """List filter IDs usable with krita_apply_filter."""
    result = send_command("list_filters", {})

    if "error" in result:
        return f"Error: {result['error']}"

    filters = result.get("filters", [])
    return f"Available filters ({len(filters)}):\n" + "\n".join(f"  - {f}" for f in filters)


@mcp.tool()
def krita_apply_filter(name: str, layer: Optional[str] = None, config: Optional[dict] = None) -> str:
    """
    Apply a named filter destructively to a layer's full bounds.

    Args:
        name: Filter ID (see krita_list_filters)
        layer: Layer name (default: active layer)
        config: Optional dict of filter-specific configuration properties
    """
    params = {"name": name}
    if layer:
        params["layer"] = layer
    if config:
        params["config"] = config
    result = send_command("apply_filter", params, timeout=60.0)

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Applied filter '{name}' to layer '{result.get('layer')}'"


# --- Document ---

@mcp.tool()
def krita_document_info() -> str:
    """Report dimensions, color space, and file info for the active document."""
    result = send_command("document_info", {})

    if "error" in result:
        return f"Error: {result['error']}"
    return (
        f"{result.get('name')} ({result.get('fileName') or 'unsaved'})\n"
        f"{result.get('width')}x{result.get('height')} @ {result.get('resolution')}ppi\n"
        f"Color: {result.get('colorModel')} {result.get('colorDepth')}, profile: {result.get('colorProfile')}"
    )


@mcp.tool()
def krita_set_color_space(color_model: str, color_depth: str, color_profile: str) -> str:
    """
    Convert the active document's color space. Use krita_list_color_profiles to find valid
    combinations. For an HDR-capable canvas, try color_depth="F16" or "F32" with a scene-linear
    profile (exact profile names vary by Krita install).

    Args:
        color_model: e.g. "RGBA", "LABA", "CMYKA"
        color_depth: e.g. "U8", "U16", "F16", "F32"
        color_profile: Profile name (see krita_list_color_profiles)
    """
    result = send_command("set_color_space", {
        "color_model": color_model,
        "color_depth": color_depth,
        "color_profile": color_profile,
    })

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Color space set to {color_model}/{color_depth}/{color_profile}"


@mcp.tool()
def krita_list_color_profiles(color_model: str = "RGBA", color_depth: str = "U8") -> str:
    """List color profile names available for a given color model + depth."""
    result = send_command("list_color_profiles", {"color_model": color_model, "color_depth": color_depth})

    if "error" in result:
        return f"Error: {result['error']}"

    profiles = result.get("profiles", [])
    return f"Profiles for {color_model}/{color_depth} ({len(profiles)}):\n" + "\n".join(f"  - {p}" for p in profiles)


@mcp.tool()
def krita_list_documents() -> str:
    """List all open documents."""
    result = send_command("list_documents", {})

    if "error" in result:
        return f"Error: {result['error']}"

    docs = result.get("documents", [])
    if not docs:
        return "No documents open"
    return "\n".join(
        f"  - {d['name']} ({d['width']}x{d['height']}) {d['fileName'] or 'unsaved'}" for d in docs
    )


@mcp.tool()
def krita_close_document(name: Optional[str] = None) -> str:
    """Close a document by name, or the active document if no name given."""
    result = send_command("close_document", {"name": name} if name else {})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Closed '{result.get('name')}'"


@mcp.tool()
def krita_resize_canvas(x: int, y: int, width: int, height: int) -> str:
    """
    Resize the canvas without scaling pixels (repositions the content origin).

    Args:
        x, y: New position of the current content's top-left corner
        width, height: New canvas dimensions
    """
    result = send_command("resize_canvas", {"x": x, "y": y, "width": width, "height": height})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Canvas resized to {width}x{height}"


@mcp.tool()
def krita_crop_canvas(x: int, y: int, width: int, height: int) -> str:
    """Crop the canvas to a rectangle."""
    result = send_command("crop_canvas", {"x": x, "y": y, "width": width, "height": height})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Canvas cropped to {width}x{height} at ({x}, {y})"


@mcp.tool()
def krita_flatten_image() -> str:
    """Flatten all layers of the active document into one."""
    result = send_command("flatten_image", {})

    if "error" in result:
        return f"Error: {result['error']}"
    return "Image flattened"


@mcp.tool()
def krita_export_layer(path: str, name: Optional[str] = None) -> str:
    """
    Export a single layer (default: active layer) to an image file, independent of the full canvas.

    Args:
        path: Full output file path
        name: Layer name (default: active layer)
    """
    params = {"path": path}
    if name:
        params["name"] = name
    result = send_command("export_layer", params, timeout=60.0)

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Exported layer '{result.get('name')}' to {result.get('path')}"


if __name__ == "__main__":
    mcp.run()
