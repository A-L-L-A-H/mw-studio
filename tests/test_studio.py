"""Unit tests for mw-studio poster (CAN-0011), clipper, worker, and HTTP server."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import unittest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mw_studio.clipper import (
    ClipRenderError,
    ClipSpec,
    build_vertical_clip_cmd,
    render_clip,
)
from mw_studio.hf_publisher import prepare_hf_artifact, publish_to_huggingface
from mw_studio.poster import Can0011ViolationError, render_god_promise_svg
from mw_studio.reel_generator import (
    RemoteLeakGuardError,
    compile_markdown_reel,
    format_srt_timestamp,
    format_vtt_timestamp,
    parse_markdown_storyboard,
    probe_reel_dependencies,
)
from mw_studio.server import create_server
from mw_studio.tts_stt import synthesize_tts_wav, transcribe_stt_audio
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
            with (
                self.subTest(override=override),
                self.assertRaises(Can0011ViolationError),
            ):
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
        def ok_runner(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        res = render_clip(
            {
                "input_path": "in.mp4",
                "output_path": "out.mp4",
                "start_sec": 0,
                "duration_sec": 10,
            },
            runner=ok_runner,
        )
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.output_path, "out.mp4")

        def fail_runner(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="invalid stream"
            )

        with self.assertRaises(ClipRenderError):
            render_clip(
                {
                    "input_path": "in.mp4",
                    "output_path": "out.mp4",
                    "start_sec": 0,
                    "duration_sec": 10,
                },
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
            def log_message(self, format: str, *args: object) -> None:
                return

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = (
                    json.loads(self.rfile.read(length).decode("utf-8"))
                    if length
                    else {}
                )
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
            def log_message(self, format: str, *args: object) -> None:
                return

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                echo_uploads.append(self.rfile.read(length))
                resp = json.dumps(
                    {"drive": "9Drive", "object_id": "obj-9drive-1"}
                ).encode("utf-8")
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

    def _request(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> tuple[int, str, bytes]:
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


class TtsSttAndHfPublisherTests(unittest.TestCase):
    def test_tts_and_stt_roundtrip_and_can0011_guard(self) -> None:
        tts_res = synthesize_tts_wav(
            {
                "text": "Bismillah, signal clarity across RockSoul horizon.",
                "voice": "id-ID-ArdiNeural",
                "sample_rate": 16000,
                "duration_sec": 0.1,
            }
        )
        self.assertTrue(tts_res.audio_wav.startswith(b"RIFF"))
        self.assertEqual(len(tts_res.sha256), 64)

        stt_res = transcribe_stt_audio(
            tts_res.audio_wav,
            language="id",
            prompt_hint="Bismillah, signal clarity across RockSoul horizon.",
        )
        self.assertEqual(stt_res.audio_sha256, tts_res.sha256)
        self.assertEqual(stt_res.language, "id")
        self.assertEqual(len(stt_res.segments), 1)
        self.assertIn("RockSoul", stt_res.transcript)

        with self.assertRaises(Can0011ViolationError):
            synthesize_tts_wav({"text": "draw a portrait of Allah in golden light"})

    def test_hf_publisher_dry_run_and_custom_transport(self) -> None:
        artifact = prepare_hf_artifact("posters/card-01.svg", "<svg>GOD PROMISE</svg>")
        self.assertEqual(len(artifact.sha256), 64)

        dry_receipt = publish_to_huggingface(
            "moonwitness/studio-cards",
            [artifact],
            dry_run=True,
        )
        self.assertTrue(dry_receipt.dry_run)
        self.assertEqual(dry_receipt.file_count, 1)

        captured: list[tuple[str, dict[str, str], bytes]] = []

        def fake_transport(
            url: str, headers: dict[str, str], body: bytes
        ) -> dict[str, object]:
            captured.append((url, headers, body))
            return {
                "commitUrl": "https://huggingface.co/datasets/moonwitness/studio-cards/commit/abc1234"
            }

        live_receipt = publish_to_huggingface(
            "moonwitness/studio-cards",
            [artifact],
            token="hf_test_token_123",
            transport=fake_transport,
        )
        self.assertFalse(live_receipt.dry_run)
        self.assertEqual(len(captured), 1)
        self.assertTrue(live_receipt.commit_url.endswith("/abc1234"))

        with self.assertRaises(Can0011ViolationError):
            prepare_hf_artifact("bad.txt", "visual illustration of Prophet Muhammad")


class ReelGeneratorV63Tests(unittest.TestCase):
    def test_markdown_to_9_16_storyboard_tts_and_ffmpeg_subtitles(self) -> None:
        sample_markdown = """# Frontier Epistemic Digest
## Quantum & Sharia Ledger Alignment
- Zero-trust cryptographic proofs protect every transaction in the Mizan ledger.
- Local-first Edge-TTS voice synthesis prevents external telemetry leaks.
> Indeed, with hardship comes ease and clarity of purpose.
"""
        compiled = compile_markdown_reel(
            {
                "markdown": sample_markdown,
                "corpus_ref": "QS. Ash-Sharh 94:5-6 · V63",
                "voice": "id-ID-ArdiNeural",
                "background_input_path": "/local/media/bg.mp4",
                "output_video_path": "/local/media/out-9x16.mp4",
                "subtitle_output_path": "/local/media/out-9x16.srt",
            }
        )
        self.assertEqual(compiled.storyboard.title, "Frontier Epistemic Digest")
        self.assertEqual(compiled.storyboard.width, 1080)
        self.assertEqual(compiled.storyboard.height, 1920)
        self.assertEqual(compiled.storyboard.can_0011, "enforced")
        self.assertTrue(compiled.storyboard.local_first)
        self.assertEqual(len(compiled.storyboard.scenes), 3)
        self.assertEqual(len(compiled.tts_segments), 3)
        self.assertGreater(compiled.storyboard.total_duration_sec, 6.0)
        self.assertIn("00:00:00,000 -->", compiled.srt_subtitles)
        self.assertIn("WEBVTT", compiled.vtt_subtitles)
        self.assertTrue(compiled.combined_audio_wav.startswith(b"RIFF"))
        self.assertEqual(len(compiled.audio_sha256), 64)
        self.assertEqual(len(compiled.manifest_sha256), 64)
        self.assertIn(
            "scale=1080:1920:force_original_aspect_ratio=increase",
            " ".join(compiled.ffmpeg_command),
        )
        self.assertIn(
            "subtitles='/local/media/out-9x16.srt'", " ".join(compiled.ffmpeg_command)
        )
        for scene in compiled.storyboard.scenes:
            self.assertIn("<svg", scene.poster_svg)
            self.assertIn("CAN-0011 ANICONIC VERIFIED", scene.poster_svg)

    def test_can0011_and_local_first_remote_leak_guards(self) -> None:
        with self.assertRaises(Can0011ViolationError):
            parse_markdown_storyboard(
                {
                    "markdown": "# Bad Reel\n- Draw a visual portrait of Prophet Muhammad in the clouds.",
                }
            )

        with self.assertRaises(RemoteLeakGuardError):
            parse_markdown_storyboard(
                {
                    "markdown": "# Leak Test\n- Pulling assets from [external](https://evil.example.com/leak.mp4)",
                }
            )

        with self.assertRaises(RemoteLeakGuardError):
            compile_markdown_reel(
                {
                    "markdown": "# Clean Text\n- Local narration segment.",
                    "background_input_path": "https://cdn.external.example/video.mp4",
                }
            )

        loopback_story = parse_markdown_storyboard(
            {
                "markdown": "# Loopback Allowed\n- Local reference [echo](http://127.0.0.1:4460/asset)",
            }
        )
        self.assertEqual(len(loopback_story.scenes), 1)

    def test_dependency_probe_and_execute_ffmpeg_runner(self) -> None:
        probe = probe_reel_dependencies()
        self.assertTrue(probe.local_only_ready)
        self.assertEqual(format_srt_timestamp(65.432), "00:01:05,432")
        self.assertEqual(format_vtt_timestamp(65.432), "00:01:05.432")

        executed_cmds: list[list[str]] = []

        def fake_ffmpeg(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            executed_cmds.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="rendered", stderr="")

        compiled = compile_markdown_reel(
            {
                "markdown": "# Quick Clip\n- Single scene vertical reel.",
                "background_input_path": "local://bg.mp4",
                "output_video_path": "local://out.mp4",
                "subtitle_output_path": "local://out.srt",
                "execute_ffmpeg": True,
            },
            ffmpeg_runner=fake_ffmpeg,
        )
        self.assertEqual(len(executed_cmds), 1)
        self.assertIsNotNone(compiled.render_result)

    def test_server_reel_compile_endpoint(self) -> None:
        server = create_server(host="127.0.0.1", port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = json.dumps(
                {
                    "markdown": "# Sovereign Digest\n- First vertical reel takeaway.\n- Second takeaway.",
                    "corpus_ref": "QS. 94:5",
                }
            ).encode("utf-8")
            req = urllib_request.Request(
                f"http://127.0.0.1:{port}/api/reel/compile",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                payload = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(payload["aspect_ratio"], "9:16")
                self.assertEqual(payload["scene_count"], 2)
                self.assertEqual(payload["can_0011"], "enforced")
                self.assertTrue(payload["local_first"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
