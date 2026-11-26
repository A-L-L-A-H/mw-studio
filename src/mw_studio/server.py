"""Lightweight HTTP server for mw-studio on MW_STUDIO_PORT (default 4470)."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import time
from typing import Any

from mw_studio.clipper import build_vertical_clip_cmd
from mw_studio.poster import Can0011ViolationError, render_god_promise_svg
from mw_studio.worker import DEFAULT_CAPABILITY_TAGS

DEFAULT_STUDIO_PORT = 4470
_START_TIME = time.monotonic()


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length_header = handler.headers.get("Content-Length", "0")
    try:
        length = int(length_header)
    except ValueError as exc:
        raise ValueError("Invalid Content-Length header") from exc
    raw = handler.rfile.read(length) if length > 0 else b""
    if not raw:
        raise ValueError("Request body is required")
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("JSON body must be an object")
    return parsed


class StudioRequestHandler(BaseHTTPRequestHandler):
    """HTTP endpoints for health, status, CAN-0011 poster rendering, and 9:16 clip planning."""

    server_version = "mw-studio/0.1.0"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            _json_response(
                self,
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "service": "mw-studio",
                    "can_0011": "enforced",
                },
            )
            return

        if path == "/api/status":
            _json_response(
                self,
                HTTPStatus.OK,
                {
                    "service": "mw-studio",
                    "version": "0.1.0",
                    "port": self.server.server_address[1],
                    "capability_tags": list(DEFAULT_CAPABILITY_TAGS),
                    "can_0011": "enforced",
                    "mission_url": os.environ.get("MW_MISSION_URL", "http://127.0.0.1:4450"),
                    "echo_url": os.environ.get("MW_ECHO_URL", "http://127.0.0.1:4460"),
                    "uptime_sec": round(time.monotonic() - _START_TIME, 3),
                },
            )
            return

        _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/render/poster":
            self._handle_render_poster()
            return
        if path == "/api/clip/plan":
            self._handle_clip_plan()
            return
        _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def _handle_render_poster(self) -> None:
        try:
            payload = _read_json_body(self)
            svg = render_god_promise_svg(payload)
        except Can0011ViolationError as exc:
            _json_response(
                self,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {"error": str(exc), "code": "CAN-0011"},
            )
            return
        except (ValueError, json.JSONDecodeError) as exc:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        body = svg.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_clip_plan(self) -> None:
        try:
            payload = _read_json_body(self)
            command = build_vertical_clip_cmd(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        _json_response(
            self,
            HTTPStatus.OK,
            {
                "aspect_ratio": "9:16",
                "width": int(payload.get("width", 1080)),
                "height": int(payload.get("height", 1920)),
                "start_sec": float(payload.get("start_sec", 0.0)),
                "duration_sec": float(payload.get("duration_sec", 30.0)),
                "command": command,
            },
        )


def create_server(host: str = "0.0.0.0", port: int | None = None) -> ThreadingHTTPServer:
    """Create a configured ThreadingHTTPServer for mw-studio."""
    resolved_port = (
        int(os.environ.get("MW_STUDIO_PORT", str(DEFAULT_STUDIO_PORT)))
        if port is None
        else port
    )
    return ThreadingHTTPServer((host, resolved_port), StudioRequestHandler)


def run_server(host: str = "0.0.0.0", port: int | None = None) -> None:
    """Run the mw-studio HTTP server until interrupted."""
    server = create_server(host=host, port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
