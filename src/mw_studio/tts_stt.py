"""TTS (Text-to-Speech) & STT (Speech-to-Text) pipeline for mw-studio with CAN-0011 guard."""

from __future__ import annotations

import hashlib
import io
import math
import struct
import wave
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mw_studio.poster import validate_can_0011


@dataclass(frozen=True)
class TtsRequest:
    text: str
    voice: str = "id-ID-ArdiNeural"
    sample_rate: int = 16000
    duration_sec: float = 0.25


@dataclass(frozen=True)
class TtsResult:
    voice: str
    sample_rate: int
    audio_wav: bytes
    sha256: str
    duration_sec: float


@dataclass(frozen=True)
class SttSegment:
    start_sec: float
    end_sec: float
    text: str
    confidence: float


@dataclass(frozen=True)
class SttResult:
    language: str
    transcript: str
    segments: tuple[SttSegment, ...]
    audio_sha256: str


def synthesize_tts_wav(
    spec: TtsRequest | dict[str, Any],
    backend: Callable[[TtsRequest], bytes] | None = None,
) -> TtsResult:
    """Synthesize deterministic mono PCM WAV audio after enforcing CAN-0011."""
    if isinstance(spec, dict):
        validate_can_0011(
            visual_prompt=str(spec.get("visual_prompt", "")),
            subject=str(spec.get("subject", "")),
            label=str(spec.get("label", "")),
            reflection=str(spec.get("text", "")),
        )
        req = TtsRequest(
            text=str(spec.get("text", "")).strip(),
            voice=str(spec.get("voice", "id-ID-ArdiNeural")).strip()
            or "id-ID-ArdiNeural",
            sample_rate=int(spec.get("sample_rate", 16000)),
            duration_sec=float(spec.get("duration_sec", 0.25)),
        )
    else:
        validate_can_0011(reflection=spec.text, label=spec.voice)
        req = spec

    if not req.text:
        raise ValueError("TTS text must not be empty")
    if req.sample_rate < 8000 or req.sample_rate > 48000:
        raise ValueError("sample_rate must be between 8000 and 48000 Hz")
    if req.duration_sec <= 0 or req.duration_sec > 60.0:
        raise ValueError("duration_sec must be in (0, 60]")

    if backend is not None:
        wav_bytes = backend(req)
    else:
        wav_bytes = _build_deterministic_sine_wav(
            req.text, req.sample_rate, req.duration_sec
        )

    digest = hashlib.sha256(wav_bytes).hexdigest()
    return TtsResult(
        voice=req.voice,
        sample_rate=req.sample_rate,
        audio_wav=wav_bytes,
        sha256=digest,
        duration_sec=req.duration_sec,
    )


def _build_deterministic_sine_wav(
    text: str, sample_rate: int, duration_sec: float
) -> bytes:
    seed_hash = hashlib.sha256(text.encode("utf-8")).digest()
    freq_hz = 220.0 + float(seed_hash[0])
    total_samples = max(1, int(sample_rate * duration_sec))
    pcm_frames = bytearray()
    for idx in range(total_samples):
        sample_val = int(
            8000.0 * math.sin(2.0 * math.pi * freq_hz * (idx / sample_rate))
        )
        pcm_frames.extend(struct.pack("<h", sample_val))

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(pcm_frames))
    return buffer.getvalue()


def transcribe_stt_audio(
    audio_bytes: bytes,
    language: str = "id",
    prompt_hint: str | None = None,
    backend: Callable[[bytes, str, str | None], tuple[str, list[SttSegment]]]
    | None = None,
) -> SttResult:
    """Transcribe audio bytes into structured STT segments with SHA-256 provenance."""
    if not audio_bytes:
        raise ValueError("audio_bytes must not be empty")
    if prompt_hint:
        validate_can_0011(reflection=prompt_hint)

    audio_sha256 = hashlib.sha256(audio_bytes).hexdigest()
    normalized_lang = language.strip().lower() or "id"

    if backend is not None:
        transcript, segments = backend(audio_bytes, normalized_lang, prompt_hint)
    else:
        text = (prompt_hint or f"transcribed-audio-{audio_sha256[:12]}").strip()
        segments = [
            SttSegment(
                start_sec=0.0,
                end_sec=1.0,
                text=text,
                confidence=0.98,
            )
        ]
        transcript = text

    return SttResult(
        language=normalized_lang,
        transcript=transcript,
        segments=tuple(segments),
        audio_sha256=audio_sha256,
    )
