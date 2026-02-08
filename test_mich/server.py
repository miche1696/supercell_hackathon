#!/usr/bin/env python3
from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from backend.game_engine import GameEngine
from backend.tracing import new_trace_id, trace_event, trace_span


PROJECT_ROOT = Path(__file__).resolve().parent
ENGINE = GameEngine(project_root=PROJECT_ROOT)
ENGINE_LOCK = threading.Lock()


class GameRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self._trace_id = None
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def _begin_trace(self) -> str:
        incoming = self.headers.get("X-Trace-Id", "").strip()
        trace_id = incoming or new_trace_id()
        self._trace_id = trace_id
        trace_event(
            "server",
            "http.request.start",
            trace_id=trace_id,
            method=self.command,
            path=self.path,
            client_ip=(self.client_address[0] if self.client_address else None),
        )
        return trace_id

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        if isinstance(payload, dict) and "trace_id" not in payload:
            payload["trace_id"] = self._trace_id or "-"

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if self._trace_id:
            self.send_header("X-Trace-Id", self._trace_id)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        trace_id = self._begin_trace()
        with trace_span("server", "do_GET", trace_id=trace_id):
            parsed = urlparse(self.path)

            if parsed.path == "/api/health":
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/state":
                with ENGINE_LOCK:
                    state = ENGINE.public_state()
                self._send_json({"ok": True, "state": state})
                return

            if parsed.path == "/":
                self.path = "/web/index.html"
                return super().do_GET()

            return super().do_GET()

    def do_POST(self) -> None:
        trace_id = self._begin_trace()
        with trace_span("server", "do_POST", trace_id=trace_id):
            parsed = urlparse(self.path)

            if parsed.path == "/api/start":
                with trace_span("server", "api_start", trace_id=trace_id):
                    with ENGINE_LOCK:
                        state = ENGINE.reset()
                    self._send_json({"ok": True, "state": state})
                    return

            if parsed.path == "/api/submit":
                with trace_span("server", "api_submit", trace_id=trace_id):
                    try:
                        body = self._read_json_body()
                    except json.JSONDecodeError:
                        self._send_json({"ok": False, "error": "Invalid JSON body"}, status=HTTPStatus.BAD_REQUEST)
                        return

                    input_text = str(body.get("input_text", ""))
                    trace_event("server", "api_submit.input", trace_id=trace_id, input_preview=input_text[:120])

                    try:
                        with ENGINE_LOCK:
                            result = ENGINE.submit(input_text, trace_id=trace_id)
                    except Exception as exc:
                        trace_event(
                            "server",
                            "api_submit.error",
                            trace_id=trace_id,
                            level="ERROR",
                            error_type=type(exc).__name__,
                            error=str(exc),
                        )
                        self._send_json(
                            {"ok": False, "error": f"judge_error: {exc}"},
                            status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                        return

                    self._send_json({"ok": True, "result": result})
                    return

            self._send_json({"ok": False, "error": "Unknown API endpoint"}, status=HTTPStatus.NOT_FOUND)



def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), GameRequestHandler)
    print(f"Serving on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
