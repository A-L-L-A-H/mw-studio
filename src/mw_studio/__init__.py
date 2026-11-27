"""MoonWitness Media, Poster (CAN-0011) & FFmpeg Short-Clip Render Worker."""

from mw_studio.clipper import ClipRenderError, ClipRenderResult, ClipSpec, build_vertical_clip_cmd, render_clip
from mw_studio.hf_publisher import HfArtifactFile, HfPublishReceipt, prepare_hf_artifact, publish_to_huggingface
from mw_studio.poster import Can0011ViolationError, GodPromiseCard, render_god_promise_svg, validate_can_0011
from mw_studio.server import create_server, run_server
from mw_studio.tts_stt import SttResult, SttSegment, TtsRequest, TtsResult, synthesize_tts_wav, transcribe_stt_audio
from mw_studio.worker import StudioWorker, WorkerConfig

__version__ = "0.1.0"

__all__ = [
    "Can0011ViolationError",
    "ClipRenderError",
    "ClipRenderResult",
    "ClipSpec",
    "GodPromiseCard",
    "HfArtifactFile",
    "HfPublishReceipt",
    "SttResult",
    "SttSegment",
    "StudioWorker",
    "TtsRequest",
    "TtsResult",
    "WorkerConfig",
    "__version__",
    "build_vertical_clip_cmd",
    "create_server",
    "prepare_hf_artifact",
    "publish_to_huggingface",
    "render_clip",
    "render_god_promise_svg",
    "run_server",
    "synthesize_tts_wav",
    "transcribe_stt_audio",
    "validate_can_0011",
]
