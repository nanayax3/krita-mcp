"""HTTP-level checks of the plugin's request handler, without Krita.

Krita and PyQt5 are replaced by minimal stubs, the handler is served on a random local port and a
fake "main thread" answers every queued command. This shows which requests the HTTP layer accepts
and forwards to Krita.

Run:  python tests/test_http_auth.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import types
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "krita-plugin" / "kritamcp" / "__init__.py"


def install_stubs():
    krita = types.ModuleType("krita")

    class Extension:
        def __init__(self, parent=None):
            pass

    class _Krita:
        @staticmethod
        def instance():
            return _Krita()

        def addExtension(self, ext):
            pass

    krita.Extension = Extension
    krita.Krita = _Krita
    krita.InfoObject = object
    krita.Selection = object
    krita.__all__ = ["Extension", "Krita", "InfoObject", "Selection"]
    sys.modules["krita"] = krita

    qtcore = types.ModuleType("PyQt5.QtCore")
    for name in ("QTimer", "QThread", "QPointF", "QRectF"):
        setattr(qtcore, name, type(name, (), {"__init__": lambda self, *a, **k: None}))
    qtcore.pyqtSignal = lambda *a, **k: None
    qtgui = types.ModuleType("PyQt5.QtGui")
    for name in ("QColor", "QFont", "QFontMetrics", "QImage", "QPainter"):
        setattr(qtgui, name, type(name, (), {}))
    qtwidgets = types.ModuleType("PyQt5.QtWidgets")
    qtwidgets.QMessageBox = type("QMessageBox", (), {})
    pyqt5 = types.ModuleType("PyQt5")
    sys.modules.update({"PyQt5": pyqt5, "PyQt5.QtCore": qtcore, "PyQt5.QtGui": qtgui, "PyQt5.QtWidgets": qtwidgets})


def load_plugin():
    install_stubs()
    # keep any token file created by the plugin out of the real home directory
    os.environ.pop("KRITA_MCP_TOKEN_FILE", None)
    os.environ["HOME"] = os.environ["USERPROFILE"] = tempfile.mkdtemp()
    spec = importlib.util.spec_from_file_location("kritamcp_under_test", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def start(mod):
    server = HTTPServer(("127.0.0.1", 0), mod.PaintRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stop = threading.Event()

    def fake_main_thread():
        while not stop.is_set():
            item = mod.command_queue.pop()
            if item is None:
                stop.wait(0.02)
                continue
            cid, cmd = item
            mod.command_queue.set_result(cid, {"status": "ok", "executed": cmd})

    threading.Thread(target=fake_main_thread, daemon=True).start()
    return server, stop


def post(port, body, headers):
    req = urllib.request.Request(f"http://127.0.0.1:{port}", data=body.encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def check_server_py(port):
    """End to end with the real client: server.py (httpx) must get through, and get a readable error without token."""
    try:
        import fastmcp  # noqa: F401  (imported by server.py)
        import httpx  # noqa: F401
    except ImportError:
        print("  [skip] server.py end to end: fastmcp / httpx not installed")
        return 0
    os.environ["KRITA_URL"] = f"http://localhost:{port}"
    spec = importlib.util.spec_from_file_location("server_under_test", ROOT / "server.py")
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    failures = 0
    r = srv.send_command("save", {"path": "x.png"})
    ok = r.get("status") == "ok"
    failures += not ok
    print(f"  [{'ok ' if ok else 'BAD'}] server.py with the token file: {r}")
    hidden = srv.TOKEN_PATH + ".hidden"
    os.replace(srv.TOKEN_PATH, hidden)
    try:
        r = srv.send_command("save", {"path": "x.png"})
    finally:
        os.replace(hidden, srv.TOKEN_PATH)
    ok = r.get("error") == "missing or invalid token"
    failures += not ok
    print(f"  [{'ok ' if ok else 'BAD'}] server.py without the token file gets a readable error: {r}")
    return failures


def main():
    mod = load_plugin()
    server, stop = start(mod)
    port = server.server_address[1]
    if hasattr(mod, "ALLOWED_HOSTS"):  # the test serves on a random port, the plugin expects SERVER_PORT
        mod.ALLOWED_HOSTS = {f"localhost:{port}", f"127.0.0.1:{port}"}
    token = getattr(mod, "AUTH_TOKEN", None)
    payload = json.dumps({"action": "save", "params": {"path": "C:/Users/Public/pwned.png"}})

    cases = [
        # (label, headers, should the request be accepted by a protected server?)
        ("browser-style request from another site (no token)",
         {"Content-Type": "text/plain", "Origin": "https://evil.example"}, False),
        ("plain request without token", {"Content-Type": "application/json"}, False),
    ]
    if token:
        cases += [
            ("valid token", {"Content-Type": "application/json", "X-Krita-Token": token}, True),
            ("valid token but Origin header (browser)", {"Content-Type": "text/plain", "X-Krita-Token": token,
                                                         "Origin": "https://evil.example"}, False),
            ("valid token but foreign Host (DNS rebinding)", {"Content-Type": "application/json",
                                                              "X-Krita-Token": token, "Host": "evil.example"}, False),
            ("wrong token", {"Content-Type": "application/json", "X-Krita-Token": "0" * 48}, False),
        ]
    failures = 0
    print(f"plugin: {PLUGIN.relative_to(ROOT)} | token protection: {'yes' if token else 'NO'}")
    for label, headers, want_ok in cases:
        status, text = post(port, payload, headers)
        accepted = status == 200
        verdict = "ok " if accepted == want_ok else "BAD"
        failures += accepted != want_ok
        print(f"  [{verdict}] {label}: HTTP {status}" + (" -> command forwarded to Krita" if accepted else ""))
    if token:
        failures += check_server_py(port)
    stop.set()
    server.shutdown()
    print("result:", "all expectations met" if not failures else f"{failures} unexpected result(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
