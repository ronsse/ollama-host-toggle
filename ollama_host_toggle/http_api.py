"""Token-gated HTTP control API, served on the tailnet interface only.

Stdlib http.server to keep dependencies minimal. Bind defaults to the tailnet IP
(never 0.0.0.0 unless explicitly configured), and every request must carry a
matching Bearer token.
"""

from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import actions
from .config import Config


def _make_handler(cfg: Config):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ollama-host-toggle/0.2"

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not cfg.auth_token:
                return False
            header = self.headers.get("Authorization", "")
            prefix = "Bearer "
            if not header.startswith(prefix):
                return False
            return hmac.compare_digest(header[len(prefix):], cfg.auth_token)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(length)) or {}
            except (ValueError, TypeError):
                return {}

        def _guard(self) -> bool:
            if not self._authorized():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return False
            return True

        def do_GET(self) -> None:  # noqa: N802
            if not self._guard():
                return
            if self.path.rstrip("/") == "/state":
                self._send(200, actions.get_state(cfg))
            else:
                self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._guard():
                return
            path = self.path.rstrip("/")
            body = self._read_json()

            if path == "/host/on":
                ok, msg = actions.start_serving(cfg)
                if ok:
                    model = body.get("preload", cfg.default_preload)
                    if model:
                        p_ok, p_msg = actions.preload(cfg, model)
                        msg = f"{msg}; {p_msg}"
                        ok = p_ok
                self._send(200 if ok else 500, {"ok": ok, "message": msg, **actions.get_state(cfg)})

            elif path == "/host/off":
                ok, msg = actions.stop_serving(cfg)
                self._send(200 if ok else 500, {"ok": ok, "message": msg, **actions.get_state(cfg)})

            elif path == "/preload":
                model = body.get("model") or cfg.default_preload
                ok, msg = actions.preload(cfg, model)
                self._send(200 if ok else 500, {"ok": ok, "message": msg, **actions.get_state(cfg)})

            elif path == "/unload":
                model = body.get("model")
                if not model:
                    loaded = actions.get_loaded_models(cfg)
                    model = loaded[0]["name"] if loaded else None
                ok, msg = actions.unload(cfg, model) if model else (False, "no loaded model")
                self._send(200 if ok else 500, {"ok": ok, "message": msg, **actions.get_state(cfg)})

            else:
                self._send(404, {"ok": False, "error": "not found"})

        def log_message(self, *_args) -> None:
            pass

    return Handler


def serve(cfg: Config) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((cfg.http_bind, cfg.http_port), _make_handler(cfg))
    threading.Thread(target=httpd.serve_forever, name="oht-http", daemon=True).start()
    return httpd
