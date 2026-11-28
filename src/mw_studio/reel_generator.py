"""V63: Automated Markdown -> 9:16 vertical reel script/storyboard + Edge-TTS + FFmpeg subtitle compiler pipeline.

Enforces CAN-0011 aniconic visual guard and local-first execution (zero unguarded remote network leaks).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mw_studio.clipper import (
    ClipRenderResult,
    ClipSpec,
    build_vertical_clip_cmd,
    render_clip,
)
from mw_studio.poster import render_god_promise_svg, validate_can_0011
from mw_studio.tts_stt import TtsRequest, TtsResult, synthesize_tts_wav

_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.+?)\s*$")
_QUOTE_RE = re.compile(r"^\s*>\s*(.+?)\s*$")
_INLINE_MD_RE = re.compile(r"(\*\*|__|`|~~)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_REMOTE_URI_RE = re.compile(r"^(https?|ftp|s3|gs|rtmp|rtsp|ws|wss)://", re.IGNORECASE)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class RemoteLeakGuardError(PermissionError):
    """Raised when an unguarded remote URL or external endpoint is passed to the local-first reel compiler."""


@dataclass(frozen=True, slots=True)
class DependencyProbeResult:
    """Offline dependency availability snapshot for reel compilation."""

    ffmpeg_available: bool
    ffmpeg_path: str | None
    edge_tts_available: bool
    edge_tts_path: str | None
    piper_available: bool
    piper_path: str | None
    local_only_ready: bool


@dataclass(frozen=True, slots=True)
class ReelScene:
    """Single timed scene inside a 9:16 vertical storyboard."""

    index: int
    heading: str
    narration: str
    caption: str
    visual_cue: str
    start_sec: float
    end_sec: float
    duration_sec: float
    poster_svg: str


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    """Single SRT/WebVTT subtitle cue aligned to a storyboard scene."""

    index: int
    start_sec: float
    end_sec: float
    text: str


@dataclass(frozen=True, slots=True)
class ReelStoryboard:
    """Parsed 9:16 vertical reel storyboard derived from Markdown input."""

    title: str
    corpus_ref: str
    voice: str
    width: int
    height: int
    fps: int
    total_duration_sec: float
    scenes: tuple[ReelScene, ...]
    srt_subtitles: str
    vtt_subtitles: str
    can_0011: str
    local_first: bool
    sha256: str


@dataclass(frozen=True, slots=True)
class ReelCompileSpec:
    """Configuration for compiling a Markdown document into a 9:16 vertical reel package."""

    markdown: str
    title: str = "MOONWITNESS FRONTIER BRIEF"
    corpus_ref: str = "CAN-0011 · SOVEREIGN EMPIRE V3"
    voice: str = "id-ID-ArdiNeural"
    sample_rate: int = 16000
    words_per_second: float = 2.6
    min_scene_sec: float = 2.5
    max_scene_sec: float = 12.0
    width: int = 1080
    height: int = 1920
    fps: int = 30
    background_input_path: str = "local://celestial-canvas.mp4"
    output_video_path: str = "local://reel-9x16.mp4"
    subtitle_output_path: str = "local://reel-9x16.srt"
    watermark_text: str = "MoonWitness · CAN-0011"
    allow_remote: bool = False
    execute_ffmpeg: bool = False
    ffmpeg_bin: str = "ffmpeg"


@dataclass(frozen=True, slots=True)
class ReelCompileResult:
    """Complete output of the V63 Markdown -> 9:16 Reel + Edge-TTS + FFmpeg subtitle pipeline."""

    storyboard: ReelStoryboard
    tts_segments: tuple[TtsResult, ...]
    combined_audio_wav: bytes
    audio_sha256: str
    srt_subtitles: str
    vtt_subtitles: str
    ffmpeg_command: list[str]
    render_result: ClipRenderResult | None
    dependency_probe: DependencyProbeResult
    manifest_sha256: str


def probe_reel_dependencies(ffmpeg_bin: str = "ffmpeg") -> DependencyProbeResult:
    """Probe local system binaries without making any network calls."""
    ffmpeg_path = shutil.which(ffmpeg_bin)
    edge_tts_path = shutil.which("edge-tts")
    piper_path = shutil.which("piper")
    return DependencyProbeResult(
        ffmpeg_available=ffmpeg_path is not None,
        ffmpeg_path=ffmpeg_path,
        edge_tts_available=edge_tts_path is not None,
        edge_tts_path=edge_tts_path,
        piper_available=piper_path is not None,
        piper_path=piper_path,
        local_only_ready=True,
    )


def enforce_local_first_guard(
    value: str,
    *,
    field_name: str,
    allow_remote: bool = False,
) -> None:
    """Block unguarded remote URLs or cloud leaks when local_first mode is active."""
    cleaned = value.strip()
    if not cleaned:
        return
    if _REMOTE_URI_RE.match(cleaned):
        parsed = urlparse(cleaned)
        host = (parsed.hostname or "").lower()
        if host in _LOOPBACK_HOSTS:
            return
        if not allow_remote:
            raise RemoteLeakGuardError(
                f"Local-first guard blocked unguarded remote URI in '{field_name}': {cleaned!r}"
            )


def _strip_markdown_inline(text: str, *, allow_remote: bool = False) -> str:
    for match in _MD_LINK_RE.finditer(text):
        link_target = match.group(2).strip()
        enforce_local_first_guard(
            link_target, field_name="markdown_link", allow_remote=allow_remote
        )
    without_links = _MD_LINK_RE.sub(r"\1", text)
    cleaned = _INLINE_MD_RE.sub("", without_links)
    return " ".join(cleaned.strip().split())


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds into deterministic SRT timestamp HH:MM:SS,mmm."""
    clamped = max(0.0, float(seconds))
    total_ms = round(clamped * 1000.0)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, millis = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    """Format seconds into deterministic WebVTT timestamp HH:MM:SS.mmm."""
    return format_srt_timestamp(seconds).replace(",", ".")


def compile_srt_subtitles(scenes: Sequence[ReelScene]) -> str:
    """Compile timed storyboard scenes into SubRip (.srt) subtitle text."""
    blocks: list[str] = []
    for scene in scenes:
        start_ts = format_srt_timestamp(scene.start_sec)
        end_ts = format_srt_timestamp(scene.end_sec)
        blocks.append(f"{scene.index}\n{start_ts} --> {end_ts}\n{scene.caption}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def compile_vtt_subtitles(scenes: Sequence[ReelScene]) -> str:
    """Compile timed storyboard scenes into WebVTT (.vtt) subtitle text."""
    blocks: list[str] = ["WEBVTT"]
    for scene in scenes:
        start_ts = format_vtt_timestamp(scene.start_sec)
        end_ts = format_vtt_timestamp(scene.end_sec)
        blocks.append(f"{scene.index}\n{start_ts} --> {end_ts}\n{scene.caption}")
    return "\n\n".join(blocks) + "\n"


def _coerce_compile_spec(spec: ReelCompileSpec | Mapping[str, Any]) -> ReelCompileSpec:
    if isinstance(spec, ReelCompileSpec):
        return spec
    return ReelCompileSpec(
        markdown=str(spec.get("markdown", "")),
        title=str(spec.get("title", "MOONWITNESS FRONTIER BRIEF")).strip()
        or "MOONWITNESS FRONTIER BRIEF",
        corpus_ref=str(spec.get("corpus_ref", "CAN-0011 · SOVEREIGN EMPIRE V3")).strip()
        or "CAN-0011 · SOVEREIGN EMPIRE V3",
        voice=str(spec.get("voice", "id-ID-ArdiNeural")).strip() or "id-ID-ArdiNeural",
        sample_rate=int(spec.get("sample_rate", 16000)),
        words_per_second=float(spec.get("words_per_second", 2.6)),
        min_scene_sec=float(spec.get("min_scene_sec", 2.5)),
        max_scene_sec=float(spec.get("max_scene_sec", 12.0)),
        width=int(spec.get("width", 1080)),
        height=int(spec.get("height", 1920)),
        fps=int(spec.get("fps", 30)),
        background_input_path=str(
            spec.get("background_input_path", "local://celestial-canvas.mp4")
        ).strip()
        or "local://celestial-canvas.mp4",
        output_video_path=str(
            spec.get("output_video_path", "local://reel-9x16.mp4")
        ).strip()
        or "local://reel-9x16.mp4",
        subtitle_output_path=str(
            spec.get("subtitle_output_path", "local://reel-9x16.srt")
        ).strip()
        or "local://reel-9x16.srt",
        watermark_text=str(spec.get("watermark_text", "MoonWitness · CAN-0011")).strip()
        or "MoonWitness · CAN-0011",
        allow_remote=bool(spec.get("allow_remote", False)),
        execute_ffmpeg=bool(spec.get("execute_ffmpeg", False)),
        ffmpeg_bin=str(spec.get("ffmpeg_bin", "ffmpeg")).strip() or "ffmpeg",
    )


def parse_markdown_storyboard(
    spec: ReelCompileSpec | Mapping[str, Any],
) -> ReelStoryboard:
    """Parse Markdown research/marketing brief into a CAN-0011-verified 9:16 vertical storyboard."""
    resolved = _coerce_compile_spec(spec)
    raw_md = resolved.markdown.strip()
    if not raw_md:
        raise ValueError("markdown must not be empty")
    if resolved.width <= 0 or resolved.height <= 0:
        raise ValueError("width and height must be > 0")
    if resolved.words_per_second <= 0:
        raise ValueError("words_per_second must be > 0")
    if resolved.min_scene_sec <= 0 or resolved.max_scene_sec < resolved.min_scene_sec:
        raise ValueError("invalid scene duration bounds")

    enforce_local_first_guard(
        resolved.background_input_path,
        field_name="background_input_path",
        allow_remote=resolved.allow_remote,
    )
    enforce_local_first_guard(
        resolved.output_video_path,
        field_name="output_video_path",
        allow_remote=resolved.allow_remote,
    )
    enforce_local_first_guard(
        resolved.subtitle_output_path,
        field_name="subtitle_output_path",
        allow_remote=resolved.allow_remote,
    )

    validate_can_0011(
        title=resolved.title,
        corpus_ref=resolved.corpus_ref,
        reflection=raw_md,
        label=resolved.voice,
    )

    doc_title = resolved.title
    current_heading = doc_title
    raw_segments: list[tuple[str, str]] = []
    paragraph_acc: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_acc:
            joined = " ".join(paragraph_acc).strip()
            if joined:
                raw_segments.append((current_heading, joined))
            paragraph_acc.clear()

    for raw_line in raw_md.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```"):
            flush_paragraph()
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            flush_paragraph()
            heading_text = _strip_markdown_inline(
                heading_match.group(1),
                allow_remote=resolved.allow_remote,
            )
            if heading_text:
                if doc_title == resolved.title and line.startswith("# "):
                    doc_title = heading_text
                current_heading = heading_text
            continue

        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            flush_paragraph()
            item_text = _strip_markdown_inline(
                bullet_match.group(1),
                allow_remote=resolved.allow_remote,
            )
            if item_text:
                raw_segments.append((current_heading, item_text))
            continue

        quote_match = _QUOTE_RE.match(line)
        if quote_match:
            flush_paragraph()
            quote_text = _strip_markdown_inline(
                quote_match.group(1),
                allow_remote=resolved.allow_remote,
            )
            if quote_text:
                raw_segments.append((current_heading, quote_text))
            continue

        cleaned_line = _strip_markdown_inline(line, allow_remote=resolved.allow_remote)
        if cleaned_line:
            paragraph_acc.append(cleaned_line)

    flush_paragraph()

    if not raw_segments:
        fallback_text = _strip_markdown_inline(
            raw_md, allow_remote=resolved.allow_remote
        )
        if not fallback_text:
            raise ValueError("markdown contains no narratable content")
        raw_segments.append((doc_title, fallback_text))

    scenes: list[ReelScene] = []
    cursor_sec = 0.0

    for idx, (heading, narration) in enumerate(raw_segments, start=1):
        validate_can_0011(
            title=heading,
            corpus_ref=resolved.corpus_ref,
            translation=narration,
            reflection=narration,
        )
        word_count = max(1, len(narration.split()))
        estimated_sec = word_count / resolved.words_per_second
        duration_sec = round(
            min(resolved.max_scene_sec, max(resolved.min_scene_sec, estimated_sec)),
            3,
        )
        start_sec = round(cursor_sec, 3)
        end_sec = round(cursor_sec + duration_sec, 3)
        cursor_sec = end_sec

        caption = (
            narration
            if len(narration) <= 110
            else narration[:107].rstrip(" ,;:") + "..."
        )
        visual_cue = f"9:16 aniconic geometric frame #{idx:02d} ({heading})"
        poster_svg = render_god_promise_svg(
            {
                "title": doc_title[:36].upper(),
                "subtitle": f"SCENE {idx:02d} · 9:16 VERTICAL REEL",
                "corpus_ref": resolved.corpus_ref,
                "translation": narration,
                "reflection": f"{heading} — {caption}",
                "closing_dua": "Bismillah · Local-First Sovereign Studio · CAN-0011 Verified",
                "width": resolved.width,
                "height": resolved.height,
            }
        )

        scenes.append(
            ReelScene(
                index=idx,
                heading=heading,
                narration=narration,
                caption=caption,
                visual_cue=visual_cue,
                start_sec=start_sec,
                end_sec=end_sec,
                duration_sec=duration_sec,
                poster_svg=poster_svg,
            )
        )

    srt_text = compile_srt_subtitles(scenes)
    vtt_text = compile_vtt_subtitles(scenes)
    storyboard_digest = hashlib.sha256(
        f"{doc_title}|{resolved.corpus_ref}|{resolved.voice}|{srt_text}".encode()
    ).hexdigest()

    return ReelStoryboard(
        title=doc_title,
        corpus_ref=resolved.corpus_ref,
        voice=resolved.voice,
        width=resolved.width,
        height=resolved.height,
        fps=resolved.fps,
        total_duration_sec=round(cursor_sec, 3),
        scenes=tuple(scenes),
        srt_subtitles=srt_text,
        vtt_subtitles=vtt_text,
        can_0011="enforced",
        local_first=not resolved.allow_remote,
        sha256=storyboard_digest,
    )


def compile_markdown_reel(
    spec: ReelCompileSpec | Mapping[str, Any],
    *,
    tts_backend: Callable[[TtsRequest], bytes] | None = None,
    ffmpeg_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ReelCompileResult:
    """Compile Markdown into a 9:16 storyboard, Edge-TTS audio track, SRT/VTT subtitles, and FFmpeg pipeline."""
    resolved = _coerce_compile_spec(spec)
    storyboard = parse_markdown_storyboard(resolved)
    probe = probe_reel_dependencies(ffmpeg_bin=resolved.ffmpeg_bin)

    tts_segments: list[TtsResult] = []
    audio_chunks: list[bytes] = []

    for scene in storyboard.scenes:
        synth_duration = min(1.0, max(0.08, round(scene.duration_sec * 0.08, 3)))
        tts_res = synthesize_tts_wav(
            TtsRequest(
                text=scene.narration,
                voice=resolved.voice,
                sample_rate=resolved.sample_rate,
                duration_sec=synth_duration,
            ),
            backend=tts_backend,
        )
        tts_segments.append(tts_res)
        audio_chunks.append(tts_res.audio_wav)

    combined_audio = b"".join(audio_chunks)
    audio_sha256 = hashlib.sha256(combined_audio).hexdigest()

    clip_spec = ClipSpec(
        input_path=resolved.background_input_path,
        output_path=resolved.output_video_path,
        start_sec=0.0,
        duration_sec=max(0.5, storyboard.total_duration_sec),
        width=resolved.width,
        height=resolved.height,
        fps=resolved.fps,
        subtitle_path=resolved.subtitle_output_path,
        watermark_text=resolved.watermark_text,
        ffmpeg_bin=resolved.ffmpeg_bin,
    )
    ffmpeg_command = build_vertical_clip_cmd(clip_spec)

    render_result: ClipRenderResult | None = None
    if resolved.execute_ffmpeg:
        if (
            resolved.subtitle_output_path
            and not resolved.subtitle_output_path.startswith("local://")
        ):
            sub_path = Path(resolved.subtitle_output_path)
            sub_path.parent.mkdir(parents=True, exist_ok=True)
            sub_path.write_text(storyboard.srt_subtitles, encoding="utf-8")
        render_result = render_clip(clip_spec, runner=ffmpeg_runner)

    manifest_hash = hashlib.sha256(
        f"{storyboard.sha256}:{audio_sha256}:{' '.join(ffmpeg_command)}".encode()
    ).hexdigest()

    return ReelCompileResult(
        storyboard=storyboard,
        tts_segments=tuple(tts_segments),
        combined_audio_wav=combined_audio,
        audio_sha256=audio_sha256,
        srt_subtitles=storyboard.srt_subtitles,
        vtt_subtitles=storyboard.vtt_subtitles,
        ffmpeg_command=ffmpeg_command,
        render_result=render_result,
        dependency_probe=probe,
        manifest_sha256=manifest_hash,
    )
