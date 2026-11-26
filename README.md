# mw-studio

MoonWitness Media, Poster (`CAN-0011`) & FFmpeg 9:16 Short-Clip Render Worker for `mw-mission` -> `mw-echo` (9Drive).

## Capabilities

- **Typographic SVG GOD PROMISE Poster Renderer** (`mw_studio.poster`): Enforces `CAN-0011` aniconism strictly (rejects any visual depiction request for Allah, Prophet Muhammad, or Isa/Yesus) and renders celestial dark+gold+emerald geometric SVG cards preserving `corpus_ref`, `translation`, `reflection`, and `closing_dua`.
- **FFmpeg 9:16 Short-Clip Builder & Runner** (`mw_studio.clipper`): Deterministic FFmpeg command builder (`build_vertical_clip_cmd`) and runner (`render_clip`) for `ViralCutter` / `short-video-factory` jobs.
- **Distributed Mission Worker** (`mw_studio.worker`): Polls `MW_MISSION_URL` (`/api/workers/lease`, capability tags `["media", "ffmpeg", "poster"]`), sends heartbeats, renders posters/clips, uploads artifacts to `MW_ECHO_URL` (`POST /api/storage/upload`), and reports `/api/jobs/:id/complete` or `/fail`.
- **HTTP Service** (`mw_studio.server`, default port `4470`):
  - `GET /health`
  - `GET /api/status`
  - `POST /api/render/poster`
  - `POST /api/clip/plan`

## Quick Start

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m mw_studio.server
PYTHONPATH=src python -m mw_studio.worker
```
