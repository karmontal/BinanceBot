"""Tiny stdlib HTTP server for the dashboard (no extra dependencies)."""
from __future__ import annotations

import base64
import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .data import DashboardData

log = logging.getLogger(__name__)
STATIC = os.path.join(os.path.dirname(__file__), "static")


def build_server(host: str, port: int, data: DashboardData, password: Optional[str] = None) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "BinanceBotDashboard"

        def log_message(self, fmt, *args):  # route through logging, quietly
            log.debug("%s %s", self.address_string(), fmt % args)

        def _authorized(self) -> bool:
            if not password:
                return True
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            try:
                user_pass = base64.b64decode(header[6:]).decode()
            except Exception:
                return False
            supplied = user_pass.split(":", 1)[-1]
            return hmac.compare_digest(supplied.encode(), password.encode())

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status: int = 200) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json; charset=utf-8")

        def do_GET(self):  # noqa: N802
            if not self._authorized():
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="BinanceBot"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            url = urlparse(self.path)
            try:
                if url.path in ("/", "/index.html"):
                    with open(os.path.join(STATIC, "index.html"), "rb") as fh:
                        self._send(200, fh.read(), "text/html; charset=utf-8")
                elif url.path == "/static/chart.umd.js":  # vendored Chart.js 4.4.1 (MIT)
                    with open(os.path.join(STATIC, "chart.umd.js"), "rb") as fh:
                        self._send(200, fh.read(), "application/javascript; charset=utf-8")
                elif url.path == "/favicon.ico":
                    self._send(204, b"", "image/x-icon")
                elif url.path == "/api/overview":
                    self._json(data.overview())
                elif url.path == "/api/bot":
                    name = parse_qs(url.query).get("name", [""])[0]
                    detail = data.bot_detail(name)
                    self._json(detail if detail else {"error": "not found"}, 200 if detail else 404)
                elif url.path == "/api/backtests":
                    self._json(data.backtests())
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as exc:
                log.exception("dashboard request failed")
                self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    return ThreadingHTTPServer((host, port), Handler)


def serve(config_path: str, host: str = "127.0.0.1", port: int = 8080, reports_dir: str = "reports") -> None:
    password = os.environ.get("DASHBOARD_PASSWORD") or None
    server = build_server(host, port, DashboardData(config_path, reports_dir), password)
    log.info("dashboard on http://%s:%d%s", host, port, " (password protected)" if password else "")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
