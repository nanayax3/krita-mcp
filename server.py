"""
Krita MCP Server
Bridge between Claude (or any MCP client) and Krita painting application.

Uses FastMCP to expose Krita painting tools over the Model Context Protocol,
communicating with a Krita plugin via HTTP.
"""

from fastmcp import FastMCP
import httpx
import os
from html import escape
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
def krita_draw_path(
    path: str,
    color: Optional[str] = None,
    x: int = 0,
    y: int = 0,
    scale: Optional[float] = None,
    fit: Optional[dict] = None,
    opacity: float = 1.0,
    preserve_aspect: bool = True
) -> str:
    """
    Draw a filled SVG-style path onto the active Krita layer.

    Supports M, L, H, V, C, Q, and Z path commands, including relative
    lowercase variants. Use either x/y/scale placement or a fit rectangle.

    Args:
        path: SVG path data, e.g. "M10 10 C20 0 40 0 50 10 Z"
        color: Fill color as hex. If omitted, uses Krita's foreground color.
        x: Left placement when fit is not supplied
        y: Top placement when fit is not supplied
        scale: Uniform scale when fit is not supplied
        fit: Optional rectangle dict: {"x": 0, "y": 0, "width": 100, "height": 100}
        opacity: Fill opacity from 0.0 to 1.0
        preserve_aspect: Keep original aspect ratio when fitting
    """
    params = {
        "path": path,
        "x": x,
        "y": y,
        "opacity": opacity,
        "preserve_aspect": preserve_aspect
    }
    if color is not None:
        params["color"] = color
    if scale is not None:
        params["scale"] = scale
    if fit is not None:
        params["fit"] = fit

    result = send_command("draw_path", params, timeout=120.0)

    if "error" in result:
        return f"Error: {result['error']}"

    bounds = result.get("bounds", {})
    return (
        f"Drew path at ({bounds.get('x')}, {bounds.get('y')}) "
        f"size {bounds.get('width')}x{bounds.get('height')}"
    )


@mcp.tool()
def krita_create_vector_svg(
    name: str = "Vector Layer",
    svg: Optional[str] = None,
    path: Optional[str] = None,
    color: str = "#000000",
    width: Optional[float] = None,
    height: Optional[float] = None,
    fill: Optional[str] = None,
    stroke: str = "none",
    stroke_width: float = 0,
    transform: str = ""
) -> str:
    """
    Create an editable Krita vector layer from SVG markup or one SVG path.

    Args:
        name: Name of the vector layer
        svg: Full SVG markup to import as shapes
        path: SVG path data to wrap in an SVG document
        color: Default fill color for path mode
        width: SVG width for path mode. Defaults to document width.
        height: SVG height for path mode. Defaults to document height.
        fill: Fill color for path mode. Defaults to color.
        stroke: Stroke color for path mode, or "none"
        stroke_width: Stroke width for path mode
        transform: Optional SVG transform for the path, e.g. "translate(100 100) scale(2)"
    """
    if not svg and not path:
        return "Error: Provide either svg or path"

    params = {
        "name": name,
        "color": color,
        "stroke": stroke,
        "stroke_width": stroke_width,
        "transform": transform,
    }
    if svg is not None:
        params["svg"] = svg
    if path is not None:
        params["path"] = path
    if width is not None:
        params["width"] = width
    if height is not None:
        params["height"] = height
    if fill is not None:
        params["fill"] = fill

    result = send_command("create_vector_svg", params, timeout=120.0)

    if "error" in result:
        return f"Error: {result['error']}"

    return (
        f"Created vector layer '{result.get('name')}' with "
        f"{result.get('shape_count')} shape(s)"
    )


def _rgb_to_hex(color: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def _component_bounds(mask, visited, start_x: int, start_y: int):
    """Collect one connected component from a boolean mask."""
    height, width = mask.shape
    stack = [(start_x, start_y)]
    visited[start_y, start_x] = True
    pixels = []
    min_x = max_x = start_x
    min_y = max_y = start_y

    while stack:
        x, y = stack.pop()
        pixels.append((x, y))
        if x < min_x:
            min_x = x
        elif x > max_x:
            max_x = x
        if y < min_y:
            min_y = y
        elif y > max_y:
            max_y = y

        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not visited[ny, nx]:
                visited[ny, nx] = True
                stack.append((nx, ny))

    return pixels, (min_x, min_y, max_x, max_y)


def _mask_to_rect_path(mask, scale: float, simplify: int = 1) -> str:
    """
    Convert a mask to editable SVG subpaths using horizontal pixel runs.

    This fallback is intentionally dependency-light. If OpenCV is installed,
    krita_trace_image_to_vector uses smoother contours instead.
    """
    height, width = mask.shape
    step = max(1, int(simplify))
    parts = []
    for y in range(0, height, step):
        x = 0
        while x < width:
            while x < width and not mask[y, x]:
                x += step
            if x >= width:
                break
            start = x
            while x < width and mask[y, x]:
                x += step
            end = min(width, x)
            x1 = start * scale
            y1 = y * scale
            x2 = end * scale
            y2 = min(height, y + step) * scale
            parts.append(f"M{x1:.2f} {y1:.2f}H{x2:.2f}V{y2:.2f}H{x1:.2f}Z")
    return "".join(parts)


def _mask_to_contour_paths(mask, scale: float, tolerance: float) -> list[str]:
    """Trace mask contours with OpenCV when available."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return []

    contour_mask = (mask.astype("uint8") * 255)
    contours, hierarchy = cv2.findContours(contour_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_TC89_KCOS)
    if hierarchy is None:
        return []

    paths = []
    for contour in contours:
        if len(contour) < 3:
            continue
        epsilon = max(0.5, tolerance) * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        pts = approx.reshape(-1, 2)
        if len(pts) < 3:
            continue
        commands = [f"M{pts[0][0] * scale:.2f} {pts[0][1] * scale:.2f}"]
        for x, y in pts[1:]:
            commands.append(f"L{x * scale:.2f} {y * scale:.2f}")
        commands.append("Z")
        paths.append("".join(commands))
    return paths


def _trace_image_to_svg(
    image_path: str,
    colors: int,
    min_area: int,
    max_size: int,
    tolerance: float,
    include_background: bool,
    rect_simplify: int,
) -> tuple[str, int, int, int]:
    """Trace a bitmap into flat-color SVG paths."""
    from PIL import Image
    import numpy as np

    if not os.path.exists(image_path):
        raise FileNotFoundError(image_path)

    image = Image.open(image_path).convert("RGBA")
    original_width, original_height = image.size
    largest_side = max(original_width, original_height)
    scale_down = min(1.0, max_size / largest_side) if max_size else 1.0
    if scale_down < 1.0:
        traced_size = (max(1, int(original_width * scale_down)), max(1, int(original_height * scale_down)))
        image = image.resize(traced_size, Image.Resampling.LANCZOS)

    trace_width, trace_height = image.size
    output_scale = original_width / trace_width

    opaque = Image.new("RGBA", image.size, (0, 0, 0, 0))
    opaque.alpha_composite(image)
    rgb = opaque.convert("RGB")
    quantized = rgb.quantize(colors=max(2, min(256, colors)), method=Image.Quantize.MEDIANCUT)
    labels = np.array(quantized)
    palette = quantized.getpalette()
    used_labels = sorted(np.unique(labels), key=lambda label: int((labels == label).sum()), reverse=True)

    if not include_background and used_labels:
        used_labels = used_labels[1:]

    svg_paths = []
    shape_count = 0
    for label in used_labels:
        mask = labels == label
        visited = np.zeros(mask.shape, dtype=bool)
        color = tuple(palette[int(label) * 3:int(label) * 3 + 3])
        fill = _rgb_to_hex(color)

        for y in range(trace_height):
            for x in range(trace_width):
                if not mask[y, x] or visited[y, x]:
                    continue
                component_pixels, (min_x, min_y, max_x, max_y) = _component_bounds(mask, visited, x, y)
                if len(component_pixels) < min_area:
                    continue

                component_mask = np.zeros(mask.shape, dtype=bool)
                for px, py in component_pixels:
                    component_mask[py, px] = True

                crop = component_mask[min_y:max_y + 1, min_x:max_x + 1]
                contour_paths = _mask_to_contour_paths(crop, output_scale, tolerance)
                if contour_paths:
                    offset = f"translate({min_x * output_scale:.2f} {min_y * output_scale:.2f})"
                    for path in contour_paths:
                        svg_paths.append(f'<path d="{path}" fill="{fill}" transform="{offset}"/>')
                        shape_count += 1
                else:
                    path = _mask_to_rect_path(crop, output_scale, rect_simplify)
                    if path:
                        offset = f"translate({min_x * output_scale:.2f} {min_y * output_scale:.2f})"
                        svg_paths.append(f'<path d="{path}" fill="{fill}" transform="{offset}"/>')
                        shape_count += 1

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{original_width}" height="{original_height}" '
        f'viewBox="0 0 {original_width} {original_height}">'
        + "".join(svg_paths)
        + "</svg>"
    )
    return svg, original_width, original_height, shape_count


@mcp.tool()
def krita_trace_image_to_vector(
    image_path: str,
    name: str = "Traced Vector Layer",
    colors: int = 8,
    min_area: int = 24,
    max_size: int = 512,
    tolerance: float = 0.003,
    include_background: bool = False,
    rect_simplify: int = 2,
    create_layer: bool = True,
    save_svg_path: Optional[str] = None
) -> str:
    """
    Trace a bitmap image into editable flat-color SVG vector shapes.

    This works best for icons, UI buttons, logos, and other low-color artwork.
    If OpenCV is installed, contours are traced and simplified. Otherwise the
    fallback creates editable horizontal-run paths using Pillow and NumPy.

    Args:
        image_path: Full path to the bitmap image to trace
        name: Krita vector layer name
        colors: Number of colors to quantize before tracing
        min_area: Ignore connected regions smaller than this many traced pixels
        max_size: Downscale largest side to this before tracing, for cleaner output
        tolerance: OpenCV contour simplification ratio
        include_background: Include the largest/background color as a vector shape
        rect_simplify: Fallback run height in pixels when OpenCV is unavailable
        create_layer: Import the generated SVG into Krita as a vector layer
        save_svg_path: Optional path to save the generated SVG
    """
    try:
        svg, width, height, shape_count = _trace_image_to_svg(
            image_path=image_path,
            colors=colors,
            min_area=min_area,
            max_size=max_size,
            tolerance=tolerance,
            include_background=include_background,
            rect_simplify=rect_simplify,
        )
    except Exception as e:
        return f"Error: {e}"

    if save_svg_path:
        with open(save_svg_path, "w", encoding="utf-8") as handle:
            handle.write(svg)

    if not create_layer:
        return f"Traced {shape_count} shape(s) from {width}x{height} image"

    result = send_command("create_vector_svg", {"name": name, "svg": svg}, timeout=120.0)
    if "error" in result:
        return f"Error: {result['error']}"

    return (
        f"Traced {shape_count} shape(s) from {width}x{height} image "
        f"into vector layer '{result.get('name')}'"
    )


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
