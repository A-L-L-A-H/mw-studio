"""MoonWitness Media, Poster (CAN-0011) & FFmpeg Short-Clip Render Worker."""

from mw_studio.clipper import ClipRenderError, ClipRenderResult, ClipSpec, build_vertical_clip_cmd, render_clip
from mw_studio.poster import Can0011ViolationError, GodPromiseCard, render_god_promise_svg, validate_can_0011
from mw_studio.server import create_server, run_server
from mw_studio.worker import StudioWorker, WorkerConfig

__version__ = "0.1.0"

__all__ = [
    "Can0011ViolationError",
    "ClipRenderError",
    "ClipRenderResult",
    "ClipSpec",
    "GodPromiseCard",
    "StudioWorker",
    "WorkerConfig",
    "__version__",
    "build_vertical_clip_cmd",
    "create_server",
    "render_clip",
    "render_god_promise_svg",
    "run_server",
    "validate_can_0011",
]
