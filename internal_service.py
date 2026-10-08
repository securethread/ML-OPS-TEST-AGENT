"""
A tiny *real* internal-only HTTP service for the SSRF demo.

The `fetch_url` MCP tool makes a genuine socket request to this (loopback)
service — nothing is special-cased. It stands in for a cloud metadata endpoint
and an internal admin page that a customer-facing agent should never be able to
reach, but can, because the tool has no scheme/host allow-list.

Started once by the parent process (web app or CLI) via start_once().
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config

_server: ThreadingHTTPServer | None = None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # silence
        pass

    def _send(self, code: int, body: str, ctype: str = "text/plain"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/latest/meta-data/iam/security-credentials"):
            self._send(200, json.dumps({
                "Code": "Success",
                "AccessKeyId": "ASIA-LAB-FAKE-EXAMPLE",
                "SecretAccessKey": config.FAKE_SECRETS["STRIPE_LIKE_KEY"],
                "Token": config.FAKE_SECRETS["JWT_SIGNING_SECRET"],
            }, indent=2), "application/json")
        elif self.path.startswith("/internal/admin"):
            self._send(200, "<h1>NovaBank Internal Admin</h1>"
                            f"<p>DB password: {config.FAKE_SECRETS['DB_ADMIN_PASSWORD']}</p>",
                       "text/html")
        else:
            self._send(404, "not found")


def start_once() -> None:
    """Start the service if it isn't already running (idempotent)."""
    global _server
    if _server is not None:
        return
    try:
        _server = ThreadingHTTPServer((config.SSRF_HOST, config.SSRF_PORT), _Handler)
    except OSError:
        return  # port already bound (another process) -> fine
    threading.Thread(target=_server.serve_forever, daemon=True).start()
