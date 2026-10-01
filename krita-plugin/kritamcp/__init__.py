"""
Krita MCP Bridge - HTTP server for external paint commands in Krita
Allows Claude (or any MCP client) to paint by sending commands to this plugin.
"""

from krita import *
# Krita 6 uses PyQt6; Krita 5 uses PyQt5. Krita blocks the wrong binding.
try:
    from PyQt6.QtCore import QTimer, QThread
    from PyQt6.QtGui import QColor
except ImportError:
    from PyQt5.QtCore import QTimer, QThread
    from PyQt5.QtGui import QColor
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os

# Configuration - customize these as needed
SERVER_PORT = 5678
CANVAS_OUTPUT_DIR = os.path.expanduser("~/krita-mcp-output")

class CommandQueue:
    """Thread-safe command queue for passing commands from HTTP thread to main thread."""
    def __init__(self):
        self.queue = []
        self.results = {}
        self.lock = threading.Lock()
        self.result_event = threading.Event()

    def push(self, command_id, command):
        with self.lock:
            self.queue.append((command_id, command))

    def pop(self):
        with self.lock:
            if self.queue:
                return self.queue.pop(0)
            return None

    def set_result(self, command_id, result):
        with self.lock:
            self.results[command_id] = result
        self.result_event.set()

    def get_result(self, command_id, timeout=120):
        """Wait for result with timeout.

        The default timeout of 120s is important — canvas export and save
        operations can take a long time on large canvases. The original 30s
        default caused frequent timeouts. The MCP server's send_command()
        timeout must match or exceed this value.
        """
        start = threading.Event()
        for _ in range(int(timeout * 10)):  # Check every 100ms
            with self.lock:
                if command_id in self.results:
                    result = self.results.pop(command_id)
                    return result
            self.result_event.wait(0.1)
            self.result_event.clear()
        return {"error": "Timeout waiting for command execution"}

# Global command queue
command_queue = CommandQueue()
command_counter = 0

class PaintRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for paint commands."""

    def log_message(self, format, *args):
        # Suppress HTTP logging
        pass

    def send_json_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        """Handle GET requests - mainly for health check."""
        parsed = urlparse(self.path)

        if parsed.path == '/health':
            self.send_json_response({"status": "ok", "plugin": "kritamcp"})
        elif parsed.path == '/info':
            self.send_json_response({
                "status": "ok",
                "canvas_dir": CANVAS_OUTPUT_DIR,
                "commands": [
                    "new_canvas", "set_color", "set_brush", "stroke",
                    "fill", "draw_shape", "get_canvas", "undo", "redo",
                    "clear", "save", "get_color_at", "list_brushes"
                ]
            })
        else:
            self.send_json_response({"error": "Unknown endpoint"}, 404)

    def do_POST(self):
        """Handle POST requests - paint commands."""
        global command_counter

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')

        try:
            command = json.loads(body)
        except json.JSONDecodeError:
            self.send_json_response({"error": "Invalid JSON"}, 400)
            return

        # Assign command ID and queue it
        command_counter += 1
        command_id = command_counter
        command_queue.push(command_id, command)

        # Wait for result from main thread
        result = command_queue.get_result(command_id)

        if "error" in result:
            self.send_json_response(result, 500)
        else:
            self.send_json_response(result)


class ServerThread(QThread):
    """Thread to run HTTP server without blocking Krita UI."""

    def __init__(self, port):
        super().__init__()
        self.port = port
        self.server = None

    def run(self):
        self.server = HTTPServer(('localhost', self.port), PaintRequestHandler)
        self.server.serve_forever()

    def stop(self):
        if self.server:
            self.server.shutdown()


class KritaMCPExtension(Extension):
    """Main Krita extension class."""

    def __init__(self, parent):
        super().__init__(parent)
        self.server_thread = None
        self.timer = None
        self.current_brush_size = 20
        self.current_opacity = 1.0

    def setup(self):
        """Called when extension is loaded."""
        pass

    def createActions(self, window):
        """Called when a new window is created."""
        # Ensure output directory exists
        os.makedirs(CANVAS_OUTPUT_DIR, exist_ok=True)

        # Start HTTP server
        if self.server_thread is None:
            self.server_thread = ServerThread(SERVER_PORT)
            self.server_thread.start()
            print(f"[KritaMCP] HTTP server started on port {SERVER_PORT}")

        # Start timer to process command queue
        if self.timer is None:
            self.timer = QTimer()
            self.timer.timeout.connect(self.process_commands)
            self.timer.start(50)  # Check every 50ms

    def process_commands(self):
        """Process commands from queue in main thread."""
        item = command_queue.pop()
        if item is None:
            return

        command_id, command = item
        result = self.execute_command(command)
        command_queue.set_result(command_id, result)

    def execute_command(self, command):
        """Execute a paint command and return result."""
        try:
            action = command.get("action")
            params = command.get("params", {})

            if action == "new_canvas":
                return self.cmd_new_canvas(params)
            elif action == "set_color":
                return self.cmd_set_color(params)
            elif action == "set_brush":
                return self.cmd_set_brush(params)
            elif action == "stroke":
                return self.cmd_stroke(params)
            elif action == "fill":
                return self.cmd_fill(params)
            elif action == "draw_shape":
                return self.cmd_draw_shape(params)
            elif action == "get_canvas":
                return self.cmd_get_canvas(params)
            elif action == "undo":
                return self.cmd_undo(params)
            elif action == "redo":
                return self.cmd_redo(params)
            elif action == "clear":
                return self.cmd_clear(params)
            elif action == "save":
                return self.cmd_save(params)
            elif action == "get_color_at":
                return self.cmd_get_color_at(params)
            elif action == "list_brushes":
                return self.cmd_list_brushes(params)
            elif action == "open_file":
                return self.cmd_open_file(params)
            else:
                return {"error": f"Unknown action: {action}"}

        except Exception as e:
            return {"error": str(e)}

    def get_active_document(self):
        """Get active document or return None."""
        app = Krita.instance()
        return app.activeDocument()

    def get_active_view(self):
        """Get active view or return None."""
        app = Krita.instance()
        window = app.activeWindow()
        if window:
            return window.activeView()
        return None

    def get_active_layer(self):
        """Get active paint layer."""
        doc = self.get_active_document()
        if doc:
            return doc.activeNode()
        return None

    def cmd_new_canvas(self, params):
        """Create a new canvas."""
        width = params.get("width", 800)
        height = params.get("height", 600)
        name = params.get("name", "New Canvas")
        bg_color = params.get("background", "#1a1a2e")

        app = Krita.instance()

        # Create document with background color
        doc = app.createDocument(width, height, name, "RGBA", "U8", "", 120.0)

        window = app.activeWindow()
        if window:
            window.addView(doc)

        # Create a paint layer
        root = doc.rootNode()
        layer = doc.createNode("paint", "paintlayer")
        root.addChildNode(layer, None)

        # Fill background using pixel data
        color = QColor(bg_color)
        r, g, b = color.red(), color.green(), color.blue()

        # Create pixel data for entire canvas (BGRA format)
        pixel_data = bytes([b, g, r, 255] * (width * height))
        layer.setPixelData(pixel_data, 0, 0, width, height)

        doc.refreshProjection()

        return {"status": "ok", "width": width, "height": height, "name": name}

    def cmd_set_color(self, params):
        """Set foreground color."""
        color_hex = params.get("color", "#ffffff")

        view = self.get_active_view()
        if not view:
            return {"error": "No active view"}

        color = QColor(color_hex)
        mc = ManagedColor.fromQColor(color, view.canvas())
        view.setForeGroundColor(mc)

        return {"status": "ok", "color": color_hex}

    def cmd_set_brush(self, params):
        """Set brush preset and size."""
        preset_name = params.get("preset", None)
        size = params.get("size", None)
        opacity = params.get("opacity", None)

        view = self.get_active_view()
        if not view:
            return {"error": "No active view"}

        if preset_name:
            # Find brush preset
            presets = Krita.instance().resources("preset")
            found = None
            for name, preset in presets.items():
                if preset_name.lower() in name.lower():
                    found = preset
                    break
            if found:
                view.setCurrentBrushPreset(found)
            else:
                return {"error": f"Brush preset not found: {preset_name}"}

        if size is not None:
            self.current_brush_size = size
            view.setBrushSize(size)

        if opacity is not None:
            self.current_opacity = opacity
            # Opacity is set per-stroke, store for later

        return {"status": "ok", "preset": preset_name, "size": size, "opacity": opacity}

    def cmd_stroke(self, params):
        """Paint a stroke along points using pixel-level drawing with soft edges."""
        points = params.get("points", [])
        brush_size = params.get("size", self.current_brush_size)
        hardness = params.get("hardness", 0.5)  # 0.0 = very soft, 1.0 = hard edge
        opacity = params.get("opacity", 1.0)

        if len(points) < 2:
            return {"error": "Need at least 2 points for a stroke"}

        layer = self.get_active_layer()
        if not layer:
            return {"error": "No active layer"}

        doc = self.get_active_document()
        view = self.get_active_view()

        if not view:
            return {"error": "No active view"}

        # Get current foreground color
        fg = view.foregroundColor()
        qcolor = fg.colorForCanvas(view.canvas())
        r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()

        width = doc.width()
        height = doc.height()
        radius = max(1, brush_size // 2)

        # Calculate bounding box for all points plus brush radius
        min_x = max(0, int(min(p[0] for p in points)) - radius - 2)
        min_y = max(0, int(min(p[1] for p in points)) - radius - 2)
        max_x = min(width, int(max(p[0] for p in points)) + radius + 2)
        max_y = min(height, int(max(p[1] for p in points)) + radius + 2)

        w = max_x - min_x
        h = max_y - min_y

        if w <= 0 or h <= 0:
            return {"error": "Stroke out of bounds"}

        # Get existing pixel data for the affected region
        existing = layer.pixelData(min_x, min_y, w, h)
        pixels = bytearray(existing)

        import math

        def draw_soft_circle(cx, cy, point_opacity=1.0):
            """Draw a soft circle with falloff at canvas coordinates."""
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    dist_sq = dx*dx + dy*dy
                    if dist_sq <= radius*radius:
                        px = int(cx) + dx - min_x
                        py = int(cy) + dy - min_y
                        if 0 <= px < w and 0 <= py < h:
                            # Calculate distance from center (0.0 to 1.0)
                            dist = math.sqrt(dist_sq) / radius if radius > 0 else 0

                            # Apply hardness curve
                            # hardness=1.0: sharp edge, hardness=0.0: gradual fade from center
                            if hardness >= 1.0:
                                alpha_factor = 1.0
                            else:
                                # Soft falloff: starts fading at hardness point
                                if dist < hardness:
                                    alpha_factor = 1.0
                                else:
                                    # Smooth falloff from hardness to edge
                                    falloff = (dist - hardness) / (1.0 - hardness) if hardness < 1.0 else 0
                                    alpha_factor = 1.0 - falloff

                            final_alpha = int(255 * alpha_factor * opacity * point_opacity)

                            if final_alpha > 0:
                                idx = (py * w + px) * 4
                                # Alpha blending with existing pixel
                                existing_b = pixels[idx]
                                existing_g = pixels[idx+1]
                                existing_r = pixels[idx+2]
                                existing_a = pixels[idx+3]

                                # Simple alpha blend
                                blend = final_alpha / 255.0
                                new_r = int(existing_r * (1 - blend) + r * blend)
                                new_g = int(existing_g * (1 - blend) + g * blend)
                                new_b = int(existing_b * (1 - blend) + b * blend)
                                new_a = max(existing_a, final_alpha)

                                pixels[idx] = new_b
                                pixels[idx+1] = new_g
                                pixels[idx+2] = new_r
                                pixels[idx+3] = new_a

        def draw_line(x1, y1, x2, y2):
            """Draw a line using interpolation with soft brush circles."""
            dist = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            # More steps for smoother lines
            steps = max(1, int(dist / max(1, radius / 3)))

            for i in range(steps + 1):
                t = i / steps if steps > 0 else 0
                x = x1 + t * (x2 - x1)
                y = y1 + t * (y2 - y1)
                draw_soft_circle(x, y)

        # Draw soft circles at each point and lines between them
        for i in range(len(points)):
            draw_soft_circle(points[i][0], points[i][1])
            if i > 0:
                draw_line(points[i-1][0], points[i-1][1], points[i][0], points[i][1])

        layer.setPixelData(bytes(pixels), min_x, min_y, w, h)
        doc.refreshProjection()

        return {"status": "ok", "points_count": len(points), "hardness": hardness}

    def cmd_fill(self, params):
        """Fill a circular area with current color."""
        x = params.get("x", 0)
        y = params.get("y", 0)
        radius = params.get("radius", 50)

        layer = self.get_active_layer()
        if not layer:
            return {"error": "No active layer"}

        doc = self.get_active_document()
        view = self.get_active_view()

        if not view:
            return {"error": "No active view"}

        # Get current foreground color
        fg = view.foregroundColor()
        qcolor = fg.colorForCanvas(view.canvas())
        r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()

        # Paint a filled circle using pixel data
        # Create a bounding box
        x1 = max(0, x - radius)
        y1 = max(0, y - radius)
        x2 = min(doc.width(), x + radius)
        y2 = min(doc.height(), y + radius)
        w = x2 - x1
        h = y2 - y1

        if w <= 0 or h <= 0:
            return {"error": "Fill area out of bounds"}

        # Get existing pixel data
        existing = layer.pixelData(x1, y1, w, h)
        pixels = bytearray(existing)

        # Draw circle
        for py in range(h):
            for px in range(w):
                # Check if point is in circle
                dx = (x1 + px) - x
                dy = (y1 + py) - y
                if dx*dx + dy*dy <= radius*radius:
                    idx = (py * w + px) * 4
                    pixels[idx] = b      # B
                    pixels[idx+1] = g    # G
                    pixels[idx+2] = r    # R
                    pixels[idx+3] = 255  # A

        layer.setPixelData(bytes(pixels), x1, y1, w, h)
        doc.refreshProjection()

        return {"status": "ok", "x": x, "y": y, "radius": radius}

    def cmd_draw_shape(self, params):
        """Draw a shape (rectangle, ellipse, line)."""
        shape = params.get("shape", "rectangle")
        x = params.get("x", 0)
        y = params.get("y", 0)
        width = params.get("width", 100)
        height = params.get("height", 100)
        fill = params.get("fill", True)

        layer = self.get_active_layer()
        if not layer:
            return {"error": "No active layer"}

        doc = self.get_active_document()
        view = self.get_active_view()

        if not view:
            return {"error": "No active view"}

        # Get current foreground color
        fg = view.foregroundColor()
        qcolor = fg.colorForCanvas(view.canvas())
        r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()

        if shape == "line":
            # Draw line using pixel data
            x2 = params.get("x2", x + width)
            y2 = params.get("y2", y + height)
            line_width = params.get("line_width", 2)

            # Calculate bounding box
            x1_bound = max(0, int(min(x, x2)) - line_width)
            y1_bound = max(0, int(min(y, y2)) - line_width)
            x2_bound = min(doc.width(), int(max(x, x2)) + line_width)
            y2_bound = min(doc.height(), int(max(y, y2)) + line_width)
            w = x2_bound - x1_bound
            h = y2_bound - y1_bound

            if w > 0 and h > 0:
                existing = layer.pixelData(x1_bound, y1_bound, w, h)
                pixels = bytearray(existing)

                # Draw line with thickness
                dist = max(abs(x2 - x), abs(y2 - y))
                steps = max(1, int(dist))
                radius = max(1, line_width // 2)

                for i in range(steps + 1):
                    t = i / steps if steps > 0 else 0
                    cx = x + t * (x2 - x)
                    cy = y + t * (y2 - y)
                    for dy in range(-radius, radius + 1):
                        for dx in range(-radius, radius + 1):
                            if dx*dx + dy*dy <= radius*radius:
                                px = int(cx) + dx - x1_bound
                                py = int(cy) + dy - y1_bound
                                if 0 <= px < w and 0 <= py < h:
                                    idx = (py * w + px) * 4
                                    pixels[idx] = b
                                    pixels[idx+1] = g
                                    pixels[idx+2] = r
                                    pixels[idx+3] = 255

                layer.setPixelData(bytes(pixels), x1_bound, y1_bound, w, h)
        elif shape == "rectangle" and fill:
            # Draw filled rectangle using pixel data
            x1 = max(0, int(x))
            y1 = max(0, int(y))
            x2 = min(doc.width(), int(x + width))
            y2 = min(doc.height(), int(y + height))
            w = x2 - x1
            h = y2 - y1

            if w > 0 and h > 0:
                pixel_data = bytes([b, g, r, 255] * (w * h))
                layer.setPixelData(pixel_data, x1, y1, w, h)
        elif shape == "ellipse" and fill:
            # Draw filled ellipse using pixel data
            cx = x + width / 2
            cy = y + height / 2
            rx = width / 2
            ry = height / 2

            x1 = max(0, int(x))
            y1 = max(0, int(y))
            x2 = min(doc.width(), int(x + width))
            y2 = min(doc.height(), int(y + height))
            w = x2 - x1
            h = y2 - y1

            if w > 0 and h > 0:
                existing = layer.pixelData(x1, y1, w, h)
                pixels = bytearray(existing)

                for py in range(h):
                    for px in range(w):
                        # Check if point is in ellipse
                        dx = (x1 + px - cx) / rx if rx > 0 else 0
                        dy = (y1 + py - cy) / ry if ry > 0 else 0
                        if dx*dx + dy*dy <= 1:
                            idx = (py * w + px) * 4
                            pixels[idx] = b
                            pixels[idx+1] = g
                            pixels[idx+2] = r
                            pixels[idx+3] = 255

                layer.setPixelData(bytes(pixels), x1, y1, w, h)
        else:
            return {"error": f"Shape '{shape}' with current options not supported"}

        doc.refreshProjection()

        return {"status": "ok", "shape": shape}

    def cmd_get_canvas(self, params):
        """Export current canvas to file and return path."""
        filename = params.get("filename", "canvas.png")

        doc = self.get_active_document()
        if not doc:
            return {"error": "No active document"}

        # Ensure filename has extension
        if not filename.endswith('.png'):
            filename += '.png'

        filepath = os.path.join(CANVAS_OUTPUT_DIR, filename)

        # Export image (batch mode suppresses export dialog)
        doc.setBatchmode(True)
        doc.exportImage(filepath, InfoObject())
        doc.setBatchmode(False)

        return {"status": "ok", "path": filepath}

    def cmd_undo(self, params):
        """Undo last action."""
        app = Krita.instance()
        action = app.action('edit_undo')
        if action:
            action.trigger()
            return {"status": "ok"}
        return {"error": "Could not trigger undo"}

    def cmd_redo(self, params):
        """Redo last undone action."""
        app = Krita.instance()
        action = app.action('edit_redo')
        if action:
            action.trigger()
            return {"status": "ok"}
        return {"error": "Could not trigger redo"}

    def cmd_clear(self, params):
        """Clear the canvas."""
        layer = self.get_active_layer()
        if not layer:
            return {"error": "No active layer"}

        doc = self.get_active_document()

        # Get canvas dimensions
        width = doc.width()
        height = doc.height()

        # Clear by filling with background color
        bg_color = params.get("color", "#1a1a2e")
        color = QColor(bg_color)
        r, g, b = color.red(), color.green(), color.blue()

        # Fill entire layer with color
        pixel_data = bytes([b, g, r, 255] * (width * height))
        layer.setPixelData(pixel_data, 0, 0, width, height)

        doc.refreshProjection()

        return {"status": "ok", "color": bg_color}

    def cmd_save(self, params):
        """Save to specific path."""
        filepath = params.get("path")
        if not filepath:
            return {"error": "No path specified"}

        doc = self.get_active_document()
        if not doc:
            return {"error": "No active document"}

        # Batch mode suppresses export dialog
        doc.setBatchmode(True)
        doc.exportImage(filepath, InfoObject())
        doc.setBatchmode(False)

        return {"status": "ok", "path": filepath}

    def cmd_get_color_at(self, params):
        """Get color at specific pixel (eyedropper)."""
        x = params.get("x", 0)
        y = params.get("y", 0)

        doc = self.get_active_document()
        if not doc:
            return {"error": "No active document"}

        # Get projection pixel data at point
        layer = doc.rootNode()
        pixel_data = layer.projectionPixelData(x, y, 1, 1)

        if len(pixel_data) >= 4:
            # RGBA
            b, g, r, a = pixel_data[0], pixel_data[1], pixel_data[2], pixel_data[3]
            hex_color = "#{:02x}{:02x}{:02x}".format(r, g, b)
            return {"status": "ok", "color": hex_color, "r": r, "g": g, "b": b, "a": a}

        return {"error": "Could not read pixel"}

    def cmd_list_brushes(self, params):
        """List available brush presets."""
        filter_str = params.get("filter", "")
        limit = params.get("limit", 50)

        presets = Krita.instance().resources("preset")
        brush_list = []

        for name, preset in presets.items():
            if filter_str.lower() in name.lower():
                brush_list.append(name)
                if len(brush_list) >= limit:
                    break

        return {"status": "ok", "brushes": brush_list, "count": len(brush_list)}

    def cmd_open_file(self, params):
        """Open an existing file in Krita."""
        filepath = params.get("path")
        if not filepath:
            return {"error": "No path specified"}

        if not os.path.exists(filepath):
            return {"error": f"File not found: {filepath}"}

        app = Krita.instance()

        # Open the document
        doc = app.openDocument(filepath)
        if not doc:
            return {"error": f"Failed to open: {filepath}"}

        # Add view to active window
        window = app.activeWindow()
        if window:
            window.addView(doc)

        return {"status": "ok", "path": filepath, "name": doc.name(), "width": doc.width(), "height": doc.height()}


# Register the extension
Krita.instance().addExtension(KritaMCPExtension(Krita.instance()))
