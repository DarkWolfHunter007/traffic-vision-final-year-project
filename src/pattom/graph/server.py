"""Local node editor: static page plus /nodes, /validate and /run (standard library only)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pattom.graph.engine import GraphError, run_graph, validate_graph
from pattom.graph.nodes import NODE_TYPES

EDITOR = Path(__file__).with_name("editor.html")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload) -> None:
        self._send(code, json.dumps(payload).encode())

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(200, EDITOR.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/nodes":
            self._json(200, [t.describe() for t in NODE_TYPES.values()])
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        spec = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if self.path == "/validate":
                self._json(200, {"valid": True, "order": validate_graph(spec)})
            elif self.path == "/run":
                r = run_graph(spec)
                self._json(200, {"order": r.order, "status": r.status, "errors": r.errors, "outputs": r.outputs})
            else:
                self._json(404, {"error": "not found"})
        except GraphError as error:
            self._json(422, {"valid": False, "error": str(error)})

    def log_message(self, *args) -> None:
        pass


def serve(port: int = 8765) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # local only
    print(f"Node editor at http://127.0.0.1:{port}/ (Ctrl+C to stop)")
    server.serve_forever()
