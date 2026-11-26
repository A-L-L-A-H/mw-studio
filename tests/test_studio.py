"""Unit tests for mw-studio poster (CAN-0011), clipper, worker, and HTTP server."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from urllib import error as urllib_error
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mw_studio.clipper import ClipRenderError, ClipSpec, build_vertical_clip_cmd, render_clip
from mw_studio.poster import Can0011ViolationError, render_god_promise_svg
from mw_studio.server import create_server
from mw_studio.worker import StudioWorker, WorkerConfig


class PosterTests(unittest.TestCase):
    def test_render_god_promise_svg_preserves_fields(self) -> None:
        svg = render_god_promise_svg(
            {
                "corpus_ref": "QS. Ash-Sharh 94:5-6",
                "translation": "For indeed, with hardship will be ease.",
                "reflection": "Every season of difficulty carries hidden mercy and renewal.",
                "closing_dua": "O Lord, grant us steadfastness and serene certainty.",
            }
        )
        self.assertIn("<svg", svg)
        self.assertIn("GOD PROMISE", svg)
        self.assertIn("QS. Ash-Sharh 94:5-6", svg)
        self.assertIn("For indeed, with hardship will be", svg)
        self.assertIn("ease.", svg)
        self.assertIn("Every season of difficulty carries hidden", svg)
        self.assertIn("mercy and renewal.", svg)
        self.assertIn("O Lord, grant us steadfastness", svg)
        self.assertIn("#d4af37", svg)
        self.assertIn("#10b981", svg)

    def test_can_0011_rejects_visual_depiction_of_sacred_figures(self) -> None:
        base = {
            "corpus_ref": "QS. Al-Baqarah 2:286",
            "translation": "Allah does not burden a soul beyond that it can bear.",
            "reflection": "Trust in mercy and keep moving forward.",
            "closing_dua": "Grant us strength and clarity.",
        }
        forbidden_cases = [
            {"visual_prompt": "celestial portrait of Allah in golden light"},
            {"subject": "Prophet Muhammad standing in the desert"},
            {"label": "illustration of Isa / Yesus"},
            {"reflection": "Draw a face of Prophet Muhammad on the poster."},
        ]
        for override in forbidden_cases:
            payload = dict(base, **override)
            with self.subTest(override=override):
                with self.assertRaises(Can0011ViolationError):
                    render_god_promise_svg(payload)


class ClipperTests(unittest.TestCase):
    def test_build_vertical_clip_cmd_generates_9_16_pipeline(self) -> None:
        cmd = build_vertical_clip_cmd(
            ClipSpec(
                input_path="/media/source.mp4",
                output_path="/tmp/out.mp4",
                start_sec=12.5,
                duration_sec=24.0,
                subtitle_path="/media/captions.srt",
                watermark_text="MoonWitness",
            )
        )
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("-ss", cmd)
        self.assertIn("12.500", cmd)
        self.assertIn("-t", cmd)
        self.assertIn("24.000", cmd)
        vf_index = cmd.index("-vf") + 1
        vf = cmd[vf_index]
        self.assertIn("scale=1080:1920:force_original_aspect_ratio=increase", vf)
        self.assertIn("crop=1080:1920", vf)
        self.assertIn("subtitles='/media/captions.srt'", vf)
        self.assertIn("drawtext=text='MoonWitness'", vf)
        self.assertEqual(cmd[-1], "/tmp/out.mp4")

    def test_render_clip_handles_success_and_failure(self) -> None:
        def ok_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        res = render_clip(
            {"input_path": "in.mp4", "output_path": "out.mp4", "start_sec": 0, "duration_sec": 10},
            runner=ok_runner,
        )
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.output_path, "out.mp4")

        def fail_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="invalid stream")

        with self.assertRaises(ClipRenderError):
            render_clip(
                {"input_path": "in.mp4", "output_path": "out.mp4", "start_sec": 0, "duration_sec": 10},
                runner=fail_runner,
            )


class WorkerLoopTests(unittest.TestCase):
    def test_worker_leases_renders_uploads_to_echo_and_completes(self) -> None:
        mission_events: list[tuple[str, dict[str, object]]] = []
        echo_uploads: list[bytes] = []
        jobs_queue: list[dict[str, object]] = [
            {
                "id": "job-poster-1",
                "type": "poster",
                "payload": {
                    "corpus_ref": "QS. At-Talaq 65:3",
                    "translation": "And whoever relies upon Allah - then He is sufficient for him.",
                    "reflection": "Reliance turns anxiety into quiet courage.",
                    "closing_dua": "Make us among those who trust You completely.",
                },
            },
            {
                "id": "job-poster-can0011",
                "type": "poster",
                "payload": {
                    "corpus_ref": "QS. 1:1",
                    "translation": "In the name of Allah.",
                    "reflection": "Mercy.",
                    "closing_dua": "Ameen.",
                    "subject": "portrait of Isa",
                },
            },
        ]

        class MockMissionHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                mission_events.append((self.path, body))
                if self.path == "/api/workers/lease":
                    if jobs_queue:
                        resp = json.dumps({"job": jobs_queue.pop(0)}).encode("utf-8")
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(resp)))
                        self.end_headers()
                        self.wfile.write(resp)
                    else:
                        self.send_response(HTTPStatus.NO_CONTENT)
                        self.end_headers()
                    return
                resp = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

        class MockEchoHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                echo_uploads.append(self.rfile.read(length))
                resp = json.dumps({"drive": "9Drive", "object_id": "obj-9drive-1"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

        mission_srv = ThreadingHTTPServer(("127.0.0.1", 0), MockMissionHandler)
        echo_srv = ThreadingHTTPServer(("127.0.0.1", 0), MockEchoHandler)
        t_mission = threading.Thread(target=mission_srv.serve_forever, daemon=True)
        t_echo = threading.Thread(target=echo_srv.serve_forever, daemon=True)
        t_mission.start()
        t_echo.start()
        try:
            worker = StudioWorker(
                WorkerConfig(
                    mission_url=f"http://127.0.0.1:{mission_srv.server_address[1]}",
                    echo_url=f"http://127.0.0.1:{echo_srv.server_address[1]}",
                    worker_id="mw-studio-test",
                )
            )
            self.assertTrue(worker.run_once())
            self.assertTrue(worker.run_once())
            self.assertFalse(worker.run_once())
        finally:
            mission_srv.shutdown()
            mission_srv.server_close()
            echo_srv.shutdown()
            echo_srv.server_close()

        paths = [p for p, _ in mission_events]
        self.assertIn("/api/workers/lease", paths)
        self.assertIn("/api/jobs/job-poster-1/heartbeat", paths)
        self.assertIn("/api/jobs/job-poster-1/complete", paths)
        self.assertIn("/api/jobs/job-poster-can0011/fail", paths)
        self.assertEqual(len(echo_uploads), 1)
        self.assertIn(b"QS. At-Talaq 65:3", echo_uploads[0])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server(host="127.0.0.1", port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def _request(self, method: str, path: str, body: dict[str, object] | None = None) -> tuple[int, str, bytes]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        req = urllib_request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib_request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.headers.get("Content-Type", ""), resp.read()
        except urllib_error.HTTPError as exc:
            return exc.code, exc.headers.get("Content-Type", ""), exc.read()

    def test_health_and_status_endpoints(self) -> None:
        status, _, raw = self._request("GET", "/health")
        self.assertEqual(status, 200)
        health = json.loads(raw.decode("utf-8"))
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["can_0011"], "enforced")

        status, _, raw = self._request("GET", "/api/status")
        self.assertEqual(status, 200)
        info = json.loads(raw.decode("utf-8"))
        self.assertEqual(info["service"], "mw-studio")
        self.assertEqual(info["capability_tags"], ["media", "ffmpeg", "poster"])

    def test_render_poster_and_can0011_rejection(self) -> None:
        status, content_type, raw = self._request(
            "POST",
            "/api/render/poster",
            {
                "corpus_ref": "QS. Al-Inshirah 94:5",
                "translation": "With hardship comes ease.",
                "reflection": "Hold steady through the storm.",
                "closing_dua": "O Allah, ease our affairs.",
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("image/svg+xml", content_type)
        self.assertIn(b"QS. Al-Inshirah 94:5", raw)

        status, _, raw = self._request(
            "POST",
            "/api/render/poster",
            {
                "corpus_ref": "QS. 1:1",
                "translation": "Mercy.",
                "reflection": "Peace.",
                "closing_dua": "Ameen.",
                "visual_prompt": "depict Allah in clouds",
            },
        )
        self.assertEqual(status, 422)
        err = json.loads(raw.decode("utf-8"))
        self.assertEqual(err["code"], "CAN-0011")

    def test_clip_plan_endpoint(self) -> None:
        status, _, raw = self._request(
            "POST",
            "/api/clip/plan",
            {
                "input_path": "/data/input.mp4",
                "output_path": "/data/clip.mp4",
                "start_sec": 5.0,
                "duration_sec": 15.0,
            },
        )
        self.assertEqual(status, 200)
        plan = json.loads(raw.decode("utf-8"))
        self.assertEqual(plan["aspect_ratio"], "9:16")
        self.assertEqual(plan["command"][0], "ffmpeg")


if __name__ == "__main__":
    unittest.main()
