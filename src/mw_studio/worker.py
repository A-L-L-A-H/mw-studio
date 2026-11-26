"""Distributed mw-studio worker polling mw-mission and uploading artifacts to mw-echo (9Drive)."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import socket
import tempfile
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from mw_studio.clipper import render_clip
from mw_studio.poster import render_god_promise_svg

DEFAULT_CAPABILITY_TAGS = ("media", "ffmpeg", "poster")


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Runtime configuration for StudioWorker."""

    mission_url: str = field(
        default_factory=lambda: os.environ.get("MW_MISSION_URL", "http://127.0.0.1:4450").rstrip("/")
    )
    echo_url: str = field(
        default_factory=lambda: os.environ.get("MW_ECHO_URL", "http://127.0.0.1:4460").rstrip("/")
    )
    worker_id: str = field(
        default_factory=lambda: os.environ.get("MW_WORKER_ID", f"mw-studio-{socket.gethostname()}")
    )
    capability_tags: tuple[str, ...] = DEFAULT_CAPABILITY_TAGS
    poll_interval_sec: float = field(
        default_factory=lambda: float(os.environ.get("MW_POLL_INTERVAL_SEC", "2.0"))
    )
    http_timeout_sec: float = 30.0
    auth_token: str = field(default_factory=lambda: os.environ.get("MW_WORKER_TOKEN", ""))


class StudioWorker:
    """Leases media/poster/clip jobs from mw-mission, executes them, and uploads to mw-echo."""

    def __init__(self, config: WorkerConfig | None = None) -> None:
        self.config = config or WorkerConfig()

    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        headers = {"Content-Type": content_type, "User-Agent": "mw-studio-worker/0.1.0"}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"
        return headers

    def _post_json(self, url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(url, data=body, headers=self._headers(), method="POST")
        try:
            with urllib_request.urlopen(req, timeout=self.config.http_timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw.strip() else {}
                return resp.status, parsed
        except urllib_error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                parsed = {"error": raw}
            return exc.code, parsed

    def lease_job(self) -> dict[str, Any] | None:
        """Poll mw-mission /api/workers/lease for a matching media/ffmpeg/poster job."""
        status, data = self._post_json(
            f"{self.config.mission_url}/api/workers/lease",
            {
                "worker_id": self.config.worker_id,
                "capability_tags": list(self.config.capability_tags),
            },
        )
        if status == 204:
            return None
        if status >= 400:
            raise RuntimeError(f"Lease failed ({status}): {data}")
        job = data.get("job") if isinstance(data, dict) else None
        if job:
            return job
        if isinstance(data, dict) and data.get("id"):
            return data
        return None

    def heartbeat(self, job_id: str, progress: float | None = None) -> dict[str, Any]:
        """Send a job heartbeat to mw-mission."""
        payload: dict[str, Any] = {"worker_id": self.config.worker_id}
        if progress is not None:
            payload["progress"] = progress
        status, data = self._post_json(
            f"{self.config.mission_url}/api/jobs/{job_id}/heartbeat",
            payload,
        )
        if status >= 400:
            raise RuntimeError(f"Heartbeat failed ({status}): {data}")
        return data

    def upload_artifact(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        job_id: str,
    ) -> dict[str, Any]:
        """Upload a rendered artifact to mw-echo (9Drive) POST /api/storage/upload."""
        boundary = "----mw-studio-boundary-9drive"
        parts = [
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="job_id"\r\n\r\n'
            f"{job_id}\r\n".encode("utf-8"),
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            content,
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
        body = b"".join(parts)
        headers = self._headers(f"multipart/form-data; boundary={boundary}")
        req = urllib_request.Request(
            f"{self.config.echo_url}/api/storage/upload",
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=self.config.http_timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {"status": "uploaded"}

    def complete_job(self, job_id: str, result: dict[str, Any]) -> dict[str, Any]:
        """Report successful job completion to mw-mission."""
        status, data = self._post_json(
            f"{self.config.mission_url}/api/jobs/{job_id}/complete",
            {"worker_id": self.config.worker_id, "result": result},
        )
        if status >= 400:
            raise RuntimeError(f"Complete failed ({status}): {data}")
        return data

    def fail_job(self, job_id: str, error_message: str) -> dict[str, Any]:
        """Report job failure to mw-mission."""
        status, data = self._post_json(
            f"{self.config.mission_url}/api/jobs/{job_id}/fail",
            {"worker_id": self.config.worker_id, "error": error_message},
        )
        if status >= 400:
            raise RuntimeError(f"Fail report failed ({status}): {data}")
        return data

    def execute_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Execute a leased poster or clip job and upload its output to mw-echo."""
        job_id = str(job["id"])
        job_type = str(job.get("type") or job.get("kind") or "").lower()
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}

        self.heartbeat(job_id, progress=0.1)

        if job_type in {"poster", "god_promise_poster", "svg_poster"}:
            svg_text = render_god_promise_svg(payload)
            self.heartbeat(job_id, progress=0.7)
            upload_resp = self.upload_artifact(
                filename=f"god-promise-{job_id}.svg",
                content=svg_text.encode("utf-8"),
                content_type="image/svg+xml",
                job_id=job_id,
            )
            return {
                "kind": "poster",
                "content_type": "image/svg+xml",
                "bytes": len(svg_text.encode("utf-8")),
                "artifact": upload_resp,
            }

        if job_type in {"clip", "short_clip", "viral_cutter", "short-video-factory"}:
            with tempfile.TemporaryDirectory(prefix="mw-studio-") as tmp_dir:
                output_path = str(payload.get("output_path") or Path(tmp_dir) / f"clip-{job_id}.mp4")
                clip_payload = dict(payload)
                clip_payload["output_path"] = output_path
                render_res = render_clip(clip_payload)
                self.heartbeat(job_id, progress=0.75)
                clip_bytes = Path(render_res.output_path).read_bytes()
                upload_resp = self.upload_artifact(
                    filename=Path(render_res.output_path).name,
                    content=clip_bytes,
                    content_type="video/mp4",
                    job_id=job_id,
                )
                return {
                    "kind": "clip",
                    "content_type": "video/mp4",
                    "bytes": len(clip_bytes),
                    "command": render_res.command,
                    "artifact": upload_resp,
                }

        raise ValueError(f"Unsupported job type: {job_type!r}")

    def run_once(self) -> bool:
        """Lease and process at most one job. Returns True if a job was processed."""
        job = self.lease_job()
        if not job:
            return False
        job_id = str(job["id"])
        try:
            result = self.execute_job(job)
            self.complete_job(job_id, result)
        except Exception as exc:  # noqa: BLE001
            self.fail_job(job_id, str(exc))
        return True

    def run_forever(self) -> None:
        """Continuously poll mw-mission until interrupted."""
        while True:
            processed = self.run_once()
            if not processed:
                time.sleep(self.config.poll_interval_sec)


if __name__ == "__main__":
    StudioWorker().run_forever()
