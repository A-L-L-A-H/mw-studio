# mw-studio — Media, poster, and FFmpeg short-clip worker for mw-mission jobs.

**Repository:** [`A-L-L-A-H/mw-studio`](https://github.com/A-L-L-A-H/mw-studio) · **Stack:** Python 3.12+

## What it does

Renders CAN-0011 typographic SVG posters, builds deterministic 9:16 clips, leases jobs from mw-mission, and uploads artifacts to mw-echo 9Drive.

## Quick start

```bash
PYTHONPATH=src python -m mw_studio.server
PYTHONPATH=src python -m mw_studio.worker
```

## Verify

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Configuration

- **Port:** 4470
- **Key configuration:** MW_STUDIO_PORT · MW_MISSION_URL · MW_ECHO_URL

```bash
docker build -t ghcr.io/a-l-l-a-h/mw-studio:latest .
```

## Notes

FFmpeg is required for clip rendering. The worker advertises media, ffmpeg, and poster capability tags.
