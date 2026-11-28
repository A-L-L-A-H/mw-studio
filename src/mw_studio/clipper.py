"""FFmpeg 9:16 vertical short-clip command builder and runner."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass


class ClipRenderError(RuntimeError):
    """Raised when FFmpeg clip rendering fails."""


@dataclass(frozen=True, slots=True)
class ClipSpec:
    """Parameters for a 9:16 vertical short-clip render job."""

    input_path: str
    output_path: str
    start_sec: float = 0.0
    duration_sec: float = 30.0
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = 20
    preset: str = "veryfast"
    audio_bitrate: str = "128k"
    subtitle_path: str | None = None
    watermark_text: str | None = None
    ffmpeg_bin: str = "ffmpeg"


@dataclass(frozen=True, slots=True)
class ClipRenderResult:
    """Structured result of executing an FFmpeg vertical clip render."""

    command: list[str]
    returncode: int
    output_path: str
    stdout: str
    stderr: str


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )


def _escape_filter_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _coerce_spec(spec: ClipSpec | Mapping[str, object]) -> ClipSpec:
    if isinstance(spec, ClipSpec):
        return spec
    return ClipSpec(
        input_path=str(spec.get("input_path", "")).strip(),
        output_path=str(spec.get("output_path", "")).strip(),
        start_sec=float(spec.get("start_sec", 0.0)),
        duration_sec=float(spec.get("duration_sec", 30.0)),
        width=int(spec.get("width", 1080)),
        height=int(spec.get("height", 1920)),
        fps=int(spec.get("fps", 30)),
        crf=int(spec.get("crf", 20)),
        preset=str(spec.get("preset", "veryfast")).strip() or "veryfast",
        audio_bitrate=str(spec.get("audio_bitrate", "128k")).strip() or "128k",
        subtitle_path=str(spec["subtitle_path"]).strip()
        if spec.get("subtitle_path")
        else None,
        watermark_text=str(spec["watermark_text"]).strip()
        if spec.get("watermark_text")
        else None,
        ffmpeg_bin=str(spec.get("ffmpeg_bin", "ffmpeg")).strip() or "ffmpeg",
    )


def build_vertical_clip_cmd(spec: ClipSpec | Mapping[str, object]) -> list[str]:
    """Build a deterministic FFmpeg command for 9:16 vertical short clips."""
    resolved = _coerce_spec(spec)
    if not resolved.input_path:
        raise ValueError("input_path is required")
    if not resolved.output_path:
        raise ValueError("output_path is required")
    if resolved.start_sec < 0:
        raise ValueError("start_sec must be >= 0")
    if resolved.duration_sec <= 0:
        raise ValueError("duration_sec must be > 0")
    if resolved.width <= 0 or resolved.height <= 0:
        raise ValueError("width and height must be > 0")
    if resolved.fps <= 0:
        raise ValueError("fps must be > 0")
    if not 0 <= resolved.crf <= 51:
        raise ValueError("crf must be between 0 and 51")

    filters = [
        f"scale={resolved.width}:{resolved.height}:force_original_aspect_ratio=increase",
        f"crop={resolved.width}:{resolved.height}",
        "setsar=1",
    ]
    if resolved.subtitle_path:
        filters.append(f"subtitles='{_escape_filter_path(resolved.subtitle_path)}'")
    if resolved.watermark_text:
        safe_wm = _escape_drawtext(resolved.watermark_text)
        filters.append(
            f"drawtext=text='{safe_wm}':fontcolor=white@0.85:fontsize=28:"
            "x=(w-text_w)/2:y=h-96"
        )

    return [
        resolved.ffmpeg_bin,
        "-y",
        "-ss",
        f"{resolved.start_sec:.3f}",
        "-i",
        resolved.input_path,
        "-t",
        f"{resolved.duration_sec:.3f}",
        "-vf",
        ",".join(filters),
        "-r",
        str(resolved.fps),
        "-c:v",
        "libx264",
        "-preset",
        resolved.preset,
        "-crf",
        str(resolved.crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        resolved.audio_bitrate,
        "-movflags",
        "+faststart",
        resolved.output_path,
    ]


def render_clip(
    spec: ClipSpec | Mapping[str, object],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_sec: int = 600,
) -> ClipRenderResult:
    """Execute the FFmpeg 9:16 vertical short-clip command and return structured output."""
    resolved = _coerce_spec(spec)
    command = build_vertical_clip_cmd(resolved)
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_sec,
        )
    except FileNotFoundError as exc:
        raise ClipRenderError(
            f"FFmpeg binary not found: {resolved.ffmpeg_bin}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ClipRenderError(f"FFmpeg timed out after {timeout_sec}s") from exc

    if completed.returncode != 0:
        raise ClipRenderError(
            f"FFmpeg exited with code {completed.returncode}: {completed.stderr.strip()}"
        )

    return ClipRenderResult(
        command=command,
        returncode=completed.returncode,
        output_path=resolved.output_path,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
