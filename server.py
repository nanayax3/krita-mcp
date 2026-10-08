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
TOKEN_PATH = os.environ.get("KRITA_MCP_TOKEN_FILE", os.path.expanduser("~/.krita-mcp-token"))

mcp = FastMCP("krita-mcp")


def read_token() -> str:
    """Shared secret written by the Krita plugin when it starts (see README, Security)."""
    try:
        with open(TOKEN_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def send_command(action: str, params: dict = None, timeout: float = 30.0) -> dict:
    """Send command to Krita plugin and return result."""
    if params is None:
        params = {}

    try:
        response = httpx.post(
            KRITA_URL,
            json={"action": action, "params": params},
            headers={"X-Krita-Token": read_token()},
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


if __name__ == "__main__":
    mcp.run()
