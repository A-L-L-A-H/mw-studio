"""Typographic SVG GOD PROMISE card renderer with strict CAN-0011 enforcement."""

from __future__ import annotations

import re
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape


class Can0011ViolationError(ValueError):
    """Raised when a poster request violates CAN-0011 aniconism policy."""


_SACRED_FIGURES_RE = re.compile(
    r"\b("
    r"allah|subhanahu|ta'ala|swt|god|"
    r"muhammad|mohammed|mohammad|rasulullah|prophet\s+muhammad|nabi\s+muhammad|"
    r"isa|nabi\s+isa|isa\s+al[-\s]?masih|yesus|jesus|christ|messiah"
    r")\b",
    re.IGNORECASE,
)

_VISUAL_DEPICTION_RE = re.compile(
    r"\b("
    r"depict\w*|portrait|face|faces|facial|figure|silhouette|likeness|avatar|"
    r"draw\w*|paint\w*|sketch\w*|illustrat\w*|photograph|photo|picture|image|"
    r"statue|sculpture|idol|iconography|caricature|cartoon|anime|photorealistic|"
    r"render\s+(?:a|an|the)?\s*(?:visual|image|face|figure|portrait|person)|"
    r"visual\s+depiction|show\s+(?:the\s+)?(?:face|figure|body|person)"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class GodPromiseCard:
    """Validated content for a typographic GOD PROMISE poster card."""

    corpus_ref: str
    translation: str
    reflection: str
    closing_dua: str
    title: str = "GOD PROMISE"
    subtitle: str = "TYPOGRAPHIC CELESTIAL EDITION"
    visual_prompt: str = ""
    subject: str = ""
    label: str = ""
    width: int = 1080
    height: int = 1920


def validate_can_0011(
    *,
    visual_prompt: str = "",
    subject: str = "",
    label: str = "",
    title: str = "",
    corpus_ref: str = "",
    translation: str = "",
    reflection: str = "",
    closing_dua: str = "",
) -> None:
    """Enforce CAN-0011 strictly: forbid any visual depiction of Allah, Prophet Muhammad, or Isa/Yesus."""
    direct_visual_fields = {
        "visual_prompt": visual_prompt,
        "subject": subject,
        "label": label,
    }
    for field_name, field_value in direct_visual_fields.items():
        if not field_value:
            continue
        if _SACRED_FIGURES_RE.search(field_value):
            raise Can0011ViolationError(
                f"CAN-0011 violation in '{field_name}': visual depiction of Allah, "
                "Prophet Muhammad, or Isa/Yesus is strictly prohibited."
            )

    text_fields = {
        "title": title,
        "corpus_ref": corpus_ref,
        "translation": translation,
        "reflection": reflection,
        "closing_dua": closing_dua,
    }
    for field_name, field_value in text_fields.items():
        if not field_value:
            continue
        if _SACRED_FIGURES_RE.search(field_value) and _VISUAL_DEPICTION_RE.search(
            field_value
        ):
            raise Can0011ViolationError(
                f"CAN-0011 violation in '{field_name}': visual depiction of Allah, "
                "Prophet Muhammad, or Isa/Yesus is strictly prohibited."
            )


def _wrap_lines(text: str, max_chars: int, max_lines: int) -> list[str]:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return []
    lines = textwrap.wrap(normalized, width=max_chars)
    if len(lines) <= max_lines:
        return lines
    clipped = lines[:max_lines]
    clipped[-1] = clipped[-1].rstrip(".,;: ") + "..."
    return clipped


def _render_tspan_block(
    lines: list[str],
    *,
    x: int,
    start_y: int,
    line_height: int,
    font_size: int,
    fill: str,
    font_family: str,
    font_weight: str = "400",
    font_style: str = "normal",
) -> str:
    if not lines:
        return ""
    tspans = []
    for idx, line in enumerate(lines):
        dy = 0 if idx == 0 else line_height
        tspans.append(f'<tspan x="{x}" dy="{dy}">{escape(line)}</tspan>')
    return (
        f'<text x="{x}" y="{start_y}" text-anchor="middle" '
        f'font-family="{font_family}" font-size="{font_size}" '
        f'font-weight="{font_weight}" font-style="{font_style}" fill="{fill}">'
        + "".join(tspans)
        + "</text>"
    )


def render_god_promise_svg(card: GodPromiseCard | Mapping[str, object]) -> str:
    """Render a clean typographic/geometric celestial dark+gold+emerald SVG poster."""
    if isinstance(card, Mapping):
        resolved = GodPromiseCard(
            corpus_ref=str(card.get("corpus_ref", "")).strip(),
            translation=str(card.get("translation", "")).strip(),
            reflection=str(card.get("reflection", "")).strip(),
            closing_dua=str(card.get("closing_dua", "")).strip(),
            title=str(card.get("title", "GOD PROMISE")).strip() or "GOD PROMISE",
            subtitle=str(card.get("subtitle", "TYPOGRAPHIC CELESTIAL EDITION")).strip(),
            visual_prompt=str(card.get("visual_prompt", "")).strip(),
            subject=str(card.get("subject", "")).strip(),
            label=str(card.get("label", "")).strip(),
            width=int(card.get("width", 1080)),
            height=int(card.get("height", 1920)),
        )
    else:
        resolved = card

    if not resolved.corpus_ref:
        raise ValueError("corpus_ref is required")
    if not resolved.translation:
        raise ValueError("translation is required")
    if not resolved.reflection:
        raise ValueError("reflection is required")
    if not resolved.closing_dua:
        raise ValueError("closing_dua is required")
    if resolved.width < 320 or resolved.height < 320:
        raise ValueError("width and height must be at least 320")

    validate_can_0011(
        visual_prompt=resolved.visual_prompt,
        subject=resolved.subject,
        label=resolved.label,
        title=resolved.title,
        corpus_ref=resolved.corpus_ref,
        translation=resolved.translation,
        reflection=resolved.reflection,
        closing_dua=resolved.closing_dua,
    )

    width = resolved.width
    height = resolved.height
    cx = width // 2

    translation_lines = _wrap_lines(resolved.translation, max_chars=34, max_lines=7)
    reflection_lines = _wrap_lines(resolved.reflection, max_chars=44, max_lines=6)
    dua_lines = _wrap_lines(resolved.closing_dua, max_chars=42, max_lines=4)

    translation_svg = _render_tspan_block(
        translation_lines,
        x=cx,
        start_y=640,
        line_height=62,
        font_size=44,
        fill="#f8fafc",
        font_family="Georgia, 'Times New Roman', serif",
        font_weight="600",
    )
    reflection_svg = _render_tspan_block(
        reflection_lines,
        x=cx,
        start_y=1145,
        line_height=46,
        font_size=30,
        fill="#d1fae5",
        font_family="'Segoe UI', Helvetica, Arial, sans-serif",
        font_weight="400",
    )
    dua_svg = _render_tspan_block(
        dua_lines,
        x=cx,
        start_y=1545,
        line_height=44,
        font_size=30,
        fill="#f3d98b",
        font_family="Georgia, 'Times New Roman', serif",
        font_weight="500",
        font_style="italic",
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 1080 1920" role="img" aria-label="{escape(resolved.title)} - {escape(resolved.corpus_ref)}">
  <defs>
    <linearGradient id="celestialBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#050811"/>
      <stop offset="50%" stop-color="#0b1526"/>
      <stop offset="100%" stop-color="#062823"/>
    </linearGradient>
    <linearGradient id="goldAccent" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#b8860b"/>
      <stop offset="50%" stop-color="#f3d98b"/>
      <stop offset="100%" stop-color="#d4af37"/>
    </linearGradient>
    <radialGradient id="emeraldHalo" cx="50%" cy="22%" r="48%">
      <stop offset="0%" stop-color="#10b981" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="#10b981" stop-opacity="0"/>
    </radialGradient>
    <pattern id="geometricGrid" width="120" height="120" patternUnits="userSpaceOnUse">
      <path d="M60 0 L120 60 L60 120 L0 60 Z" fill="none" stroke="#d4af37" stroke-opacity="0.08" stroke-width="1.2"/>
      <circle cx="60" cy="60" r="18" fill="none" stroke="#10b981" stroke-opacity="0.09" stroke-width="1"/>
    </pattern>
  </defs>

  <rect width="1080" height="1920" fill="url(#celestialBg)"/>
  <rect width="1080" height="1920" fill="url(#emeraldHalo)"/>
  <rect width="1080" height="1920" fill="url(#geometricGrid)"/>

  <rect x="44" y="44" width="992" height="1832" rx="28" fill="none" stroke="url(#goldAccent)" stroke-width="3"/>
  <rect x="64" y="64" width="952" height="1792" rx="20" fill="none" stroke="#10b981" stroke-opacity="0.45" stroke-width="1.5"/>

  <g transform="translate(540, 210)">
    <polygon points="0,-68 20,-20 68,0 20,20 0,68 -20,20 -68,0 -20,-20" fill="none" stroke="url(#goldAccent)" stroke-width="2.5"/>
    <polygon points="0,-46 14,-14 46,0 14,14 0,46 -14,14 -46,0 -14,-14" fill="#064e3b" fill-opacity="0.55" stroke="#10b981" stroke-width="1.5"/>
    <circle cx="0" cy="0" r="8" fill="#f3d98b"/>
  </g>

  <text x="540" y="345" text-anchor="middle" font-family="'Segoe UI', Helvetica, Arial, sans-serif" font-size="24" letter-spacing="8" fill="#10b981" font-weight="700">{escape(resolved.subtitle)}</text>
  <text x="540" y="418" text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-size="64" letter-spacing="6" fill="url(#goldAccent)" font-weight="700">{escape(resolved.title)}</text>

  <rect x="270" y="458" width="540" height="54" rx="27" fill="#064e3b" fill-opacity="0.65" stroke="#d4af37" stroke-width="1.5"/>
  <text x="540" y="494" text-anchor="middle" font-family="'Segoe UI', Helvetica, Arial, sans-serif" font-size="26" letter-spacing="2" fill="#f3d98b" font-weight="600">{escape(resolved.corpus_ref)}</text>

  <line x1="220" y1="560" x2="860" y2="560" stroke="url(#goldAccent)" stroke-opacity="0.6" stroke-width="1.5"/>
  {translation_svg}
  <line x1="280" y1="1065" x2="800" y2="1065" stroke="#10b981" stroke-opacity="0.55" stroke-width="1.5"/>

  <text x="540" y="1102" text-anchor="middle" font-family="'Segoe UI', Helvetica, Arial, sans-serif" font-size="20" letter-spacing="5" fill="#d4af37" font-weight="700">REFLECTION</text>
  {reflection_svg}

  <rect x="110" y="1465" width="860" height="260" rx="22" fill="#071a1c" fill-opacity="0.82" stroke="url(#goldAccent)" stroke-width="1.5"/>
  <text x="540" y="1504" text-anchor="middle" font-family="'Segoe UI', Helvetica, Arial, sans-serif" font-size="20" letter-spacing="5" fill="#10b981" font-weight="700">CLOSING DUA</text>
  {dua_svg}

  <text x="540" y="1802" text-anchor="middle" font-family="'Segoe UI', Helvetica, Arial, sans-serif" font-size="18" letter-spacing="4" fill="#94a3b8">MOONWITNESS STUDIO · CAN-0011 ANICONIC VERIFIED</text>
</svg>
"""
