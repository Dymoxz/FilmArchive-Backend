import hashlib
import hmac
import html
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import get_db
from app.models import FilmFormat, Roll

router = APIRouter(tags=["Share"])

_BASE36_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _to_base36(num: int, length: int = 8) -> str:
    chars: list[str] = []
    while num > 0:
        num, rem = divmod(num, 36)
        chars.append(_BASE36_ALPHABET[rem])
    encoded = "".join(reversed(chars)) if chars else "0"
    return encoded[-length:].rjust(length, "0")


def compute_share_code(roll: Roll) -> str:
    """
    Computes a deterministic, unguessable 8-character lowercase alphanumeric
    short code for a roll using HMAC-SHA256 with the server's secret key.
    """
    secret = settings.get_share_secret()
    payload = f"{roll.id}:{roll.folder_name}".encode("utf-8")
    digest = hmac.new(secret, payload, hashlib.sha256).digest()
    val = int.from_bytes(digest[:6], "big")
    return _to_base36(val, length=8)


def _format_display_label(film_format: FilmFormat) -> str:
    if film_format == FilmFormat.THIRTY_FIVE_MM:
        return "35MM"
    if film_format == FilmFormat.HALF_FRAME:
        return "HALF FRAME"
    if film_format == FilmFormat.MEDIUM_FORMAT:
        return "120"
    return str(film_format.value)


def _cover_url_with_version(roll: Roll) -> str:
    cover_path = (
        Path(roll.cover_image_path)
        if roll.cover_image_path
        else settings.covers_dir / f"{roll.id}.webp"
    )
    try:
        mtime_ns = cover_path.stat().st_mtime_ns
        return f"/api/rolls/{roll.id}/cover?v={mtime_ns}"
    except OSError:
        return f"/api/rolls/{roll.id}/cover"


def _render_not_found_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Roll Not Found • Film Archive</title>
<style>
  :root {
    --bg: #000000;
    --surface: #141416;
    --border: #28282C;
    --text: #F2F0EC;
    --muted: #9E9B95;
    --accent: #E5A93C;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    min-height: 100dvh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    text-align: center;
  }
  .card {
    max-width: 380px;
    padding: 32px 24px;
    border-radius: 28px;
    background: var(--surface);
    border: 1px solid var(--border);
  }
  .badge {
    display: inline-block;
    padding: 6px 12px;
    border-radius: 999px;
    background: rgba(229, 169, 60, 0.14);
    border: 1px solid rgba(229, 169, 60, 0.45);
    color: var(--accent);
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    margin-bottom: 14px;
  }
  h1 {
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin-bottom: 8px;
  }
  p {
    font-size: 14px;
    line-height: 1.5;
    color: var(--muted);
  }
</style>
</head>
<body>
  <div class="card">
    <div class="badge">404 • UNEXPOSED</div>
    <h1>Film Roll Not Found</h1>
    <p>This shared roll link is invalid or is no longer available in the archive.</p>
  </div>
</body>
</html>"""


def _render_roll_share_html(request: Request, roll: Roll) -> str:
    sorted_frames = sorted(roll.frames, key=lambda f: f.frame_number)

    base_url = str(request.base_url).rstrip("/")
    cover_path = _cover_url_with_version(roll)
    og_image_url = f"{base_url}{cover_path}"

    title_escaped = html.escape(roll.title)
    format_label = html.escape(_format_display_label(roll.film_format))
    display_date_escaped = html.escape(roll.display_date)

    start_str = roll.start_date.isoformat()
    end_str = roll.end_date.isoformat() if roll.end_date else None
    exact_date_str = (
        f"{start_str} → {end_str}"
        if end_str and end_str != start_str
        else start_str
    )
    exact_date_escaped = html.escape(exact_date_str)

    meta_parts = [f"{len(sorted_frames)} frames"]
    if roll.film_stock:
        meta_parts.append(roll.film_stock)
    if roll.camera:
        meta_parts.append(roll.camera)
    if roll.display_date:
        meta_parts.append(roll.display_date)
    og_description = html.escape(" • ".join(meta_parts))

    description_html = ""
    if roll.description and roll.description.strip():
        description_html = f'<p class="roll-description">{html.escape(roll.description)}</p>'

    # Gear chips (FILM / CAM / LENS)
    gear_chips: list[str] = []
    if roll.film_stock and roll.film_stock.strip():
        gear_chips.append(
            f'<div class="spec-chip spec-chip--highlight">'
            f'<span class="spec-dot"></span>'
            f'<span class="spec-val">{html.escape(roll.film_stock)}</span>'
            f"</div>"
        )
    if roll.camera and roll.camera.strip():
        gear_chips.append(
            f'<div class="spec-chip">'
            f'<span class="spec-tag">CAM</span>'
            f'<span class="spec-val">{html.escape(roll.camera)}</span>'
            f"</div>"
        )
    if roll.lens and roll.lens.strip():
        gear_chips.append(
            f'<div class="spec-chip">'
            f'<span class="spec-tag">LENS</span>'
            f'<span class="spec-val">{html.escape(roll.lens)}</span>'
            f"</div>"
        )
    gear_row_html = (
        f'<div class="chip-row gear-row">{"".join(gear_chips)}</div>'
        if gear_chips
        else ""
    )

    # Location chips
    location_chips: list[str] = []
    for loc in roll.location_tags or []:
        if loc and str(loc).strip():
            location_chips.append(
                f'<div class="loc-chip">'
                f'<svg class="loc-icon" viewBox="0 0 24 24" aria-hidden="true">'
                f'<path fill="currentColor" fill-rule="evenodd" d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5S10.62 6.5 12 6.5s2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>'
                f"</svg>"
                f"<span>{html.escape(str(loc).strip())}</span>"
                f"</div>"
            )
    location_row_html = (
        f'<div class="chip-row loc-row">{"".join(location_chips)}</div>'
        if location_chips
        else ""
    )

    frames_payload = [
        {
            "id": frame.id,
            "frameNumber": frame.frame_number,
            "thumbUrl": f"/api/frames/{frame.id}/thumbnail",
            "fullUrl": f"/api/frames/{frame.id}/full",
            "downloadName": f"{roll.folder_name}_frame_{frame.frame_number:02d}.jpg",
        }
        for frame in sorted_frames
    ]
    frames_json = json.dumps(frames_payload)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#000000">
<title>{title_escaped} • Film Archive</title>
<meta property="og:type" content="website">
<meta property="og:title" content="{title_escaped}">
<meta property="og:description" content="{og_description}">
<meta property="og:image" content="{og_image_url}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title_escaped}">
<meta name="twitter:description" content="{og_description}">
<meta name="twitter:image" content="{og_image_url}">
<style>
  :root {{
    --bg: #000000;
    --surface-lowest: #0A0A0C;
    --surface-low: #131316;
    --surface-high: #1D1D22;
    --outline: #38383F;
    --outline-variant: #25252B;
    --on-bg: #F3F0EA;
    --on-surface: #ECE9E2;
    --on-surface-variant: #A29E96;
    --primary: #E5A93C;
    --on-primary: #1F1400;
  }}

  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    -webkit-tap-highlight-color: transparent;
  }}

  html, body {{
    background-color: var(--bg);
    color: var(--on-bg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    min-height: 100dvh;
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
  }}

  .page-shell {{
    max-width: 920px;
    margin: 0 auto;
    padding: 20px 16px 48px;
  }}

  /* Roll Metadata Header (Mirrors RollMetadataHeader.kt) */
  .metadata-header {{
    padding: 4px 2px 6px;
  }}
  .eyebrow-row {{
    display: flex;
    align-items: center;
    gap: 4px;
    margin-bottom: 10px;
  }}
  .format-pill {{
    height: 28px;
    padding: 0 12px;
    background: var(--primary);
    color: var(--on-primary);
    border-radius: 14px 6px 6px 14px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.6px;
    text-transform: uppercase;
    user-select: none;
  }}
  .date-pill {{
    height: 28px;
    padding: 0 12px;
    background: var(--surface-high);
    border: 1px solid var(--outline-variant);
    color: var(--on-surface-variant);
    border-radius: 6px 14px 14px 6px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 11.5px;
    font-weight: 600;
    cursor: pointer;
    user-select: none;
    transition: border-color 0.18s ease, color 0.18s ease, transform 0.12s ease;
  }}
  .date-pill:active {{
    transform: scale(0.96);
  }}
  .date-pill.exact {{
    border-color: rgba(229, 169, 60, 0.7);
    color: var(--primary);
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }}

  .roll-title {{
    font-size: 28px;
    line-height: 33px;
    font-weight: 800;
    letter-spacing: -0.4px;
    color: var(--on-bg);
  }}
  .roll-description {{
    margin-top: 6px;
    font-size: 14.5px;
    line-height: 20px;
    color: var(--on-surface-variant);
  }}

  .chip-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }}
  .gear-row {{
    margin-top: 16px;
  }}
  .loc-row {{
    margin-top: 10px;
    gap: 8px;
  }}

  .spec-chip {{
    height: 28px;
    padding: 0 10px;
    border-radius: 999px;
    background: var(--surface-low);
    border: 1px solid var(--outline-variant);
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }}
  .spec-chip--highlight {{
    background: var(--surface-high);
    border-color: rgba(229, 169, 60, 0.45);
    gap: 6px;
  }}
  .spec-dot {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--primary);
    flex-shrink: 0;
  }}
  .spec-tag {{
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 9px;
    font-weight: 700;
    color: rgba(229, 169, 60, 0.85);
    letter-spacing: 0.04em;
  }}
  .spec-val {{
    font-size: 11.5px;
    font-weight: 500;
    color: var(--on-surface-variant);
  }}
  .spec-chip--highlight .spec-val {{
    font-size: 12px;
    font-weight: 600;
    color: var(--on-surface);
  }}

  .loc-chip {{
    height: 30px;
    padding: 0 12px;
    border-radius: 999px;
    background: rgba(229, 169, 60, 0.14);
    border: 1px solid rgba(229, 169, 60, 0.50);
    color: var(--primary);
    font-size: 12px;
    font-weight: 600;
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }}
  .loc-icon {{
    width: 12px;
    height: 12px;
    flex-shrink: 0;
  }}

  /* Section Header */
  .section-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 2px 10px;
  }}
  .section-label {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.8px;
    color: var(--primary);
  }}
  .section-count {{
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 12px;
    font-weight: 600;
    color: var(--on-surface-variant);
  }}

  /* 2-Column Uncropped Staggered Masonry Grid */
  .masonry-grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    align-items: start;
  }}
  @media (min-width: 720px) {{
    .masonry-grid {{
      gap: 14px;
    }}
  }}
  .masonry-col {{
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
  }}
  @media (min-width: 720px) {{
    .masonry-col {{
      gap: 14px;
    }}
  }}

  .frame-card {{
    position: relative;
    width: 100%;
    border-radius: 14px;
    overflow: hidden;
    background: var(--surface-lowest);
    border: 0.75px solid var(--outline-variant);
    cursor: zoom-in;
    transform: translateZ(0);
    transition: transform 0.2s cubic-bezier(0.2, 0.9, 0.3, 1), border-color 0.2s ease;
  }}
  .frame-card:hover {{
    border-color: rgba(229, 169, 60, 0.65);
  }}
  .frame-card:active {{
    transform: scale(0.96);
  }}
  .frame-card img {{
    display: block;
    width: 100%;
    height: auto;
    background: var(--surface-lowest);
    opacity: 0;
    transition: opacity 0.28s ease;
  }}
  .frame-card img.loaded {{
    opacity: 1;
  }}

  /* Archival Colophon Footer */
  .archive-footer {{
    margin-top: 44px;
    padding: 20px 16px 12px;
    text-align: center;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }}
  .footer-line-primary {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.4px;
    color: rgba(162, 158, 150, 0.75);
    margin-bottom: 5px;
  }}
  .footer-line-sub {{
    font-size: 9.5px;
    font-weight: 500;
    letter-spacing: 0.8px;
    line-height: 15px;
    color: rgba(162, 158, 150, 0.55);
  }}

  /* Fullscreen Lightbox Viewer */
  .lightbox {{
    position: fixed;
    inset: 0;
    z-index: 100;
    background: #000000;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.22s ease;
  }}
  .lightbox.open {{
    opacity: 1;
    pointer-events: auto;
  }}

  .lightbox-top {{
    height: 64px;
    padding: 0 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: linear-gradient(to bottom, rgba(0,0,0,0.85), rgba(0,0,0,0));
    z-index: 2;
  }}
  .icon-btn {{
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: var(--surface-high);
    border: 1px solid var(--outline);
    color: var(--on-surface);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    text-decoration: none;
    transition: transform 0.15s ease, border-color 0.15s ease;
  }}
  .icon-btn:hover {{
    border-color: var(--primary);
  }}
  .icon-btn:active {{
    transform: scale(0.92);
  }}
  .lightbox-counter {{
    height: 36px;
    padding: 0 16px;
    border-radius: 999px;
    background: var(--surface-low);
    border: 1px solid var(--outline-variant);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 12.5px;
    font-weight: 700;
    color: var(--on-surface);
  }}

  .lightbox-stage {{
    position: relative;
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    padding: 8px 12px;
    user-select: none;
  }}
  .lightbox-img {{
    max-width: 100%;
    max-height: calc(100dvh - 136px);
    width: auto;
    height: auto;
    object-fit: contain;
    border-radius: 6px;
    transition: transform 0.2s cubic-bezier(0.2, 0.9, 0.3, 1), opacity 0.18s ease;
  }}

  .nav-arrow {{
    width: 42px;
    height: 42px;
    border-radius: 50%;
    background: var(--surface-high);
    border: 1px solid var(--outline);
    color: var(--on-surface);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: opacity 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
  }}
  .nav-arrow:hover {{
    border-color: var(--primary);
  }}
  .nav-arrow:active {{
    transform: scale(0.92);
  }}

  .lightbox-bottom {{
    height: 68px;
    padding: 0 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: linear-gradient(to top, rgba(0,0,0,0.85), rgba(0,0,0,0));
    z-index: 2;
  }}
  .download-pill {{
    height: 38px;
    padding: 0 15px;
    border-radius: 999px;
    background: var(--surface-high);
    border: 1px solid var(--outline);
    color: var(--on-surface);
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 11.5px;
    font-weight: 700;
    letter-spacing: 0.5px;
    transition: border-color 0.15s ease, transform 0.15s ease;
  }}
  .download-pill:hover {{
    border-color: var(--primary);
  }}
  .download-pill:active {{
    transform: scale(0.95);
  }}
  .download-pill svg {{
    width: 15px;
    height: 15px;
    color: var(--primary);
  }}
</style>
</head>
<body>
  <div class="page-shell">
    <!-- Editorial Metadata Header -->
    <section class="metadata-header">
      <div class="eyebrow-row">
        <div class="format-pill">{format_label}</div>
        <button type="button" class="date-pill" id="datePill"
                data-display="{display_date_escaped}"
                data-exact="{exact_date_escaped}"
                title="Tap to toggle exact shoot dates">
          {display_date_escaped}
        </button>
      </div>

      <h1 class="roll-title">{title_escaped}</h1>
      {description_html}
      {gear_row_html}
      {location_row_html}
    </section>

    <!-- Frames Section Header -->
    <div class="section-header">
      <span class="section-label">FRAMES</span>
      <span class="section-count">{len(sorted_frames)}</span>
    </div>

    <!-- 2-Column Uncropped Staggered Grid -->
    <main class="masonry-grid" id="masonryGrid">
      <div class="masonry-col" id="colLeft"></div>
      <div class="masonry-col" id="colRight"></div>
    </main>

    <!-- Archival Colophon Footer -->
    <footer class="archive-footer">
      <div class="footer-line-primary">FILM PHOTOGRAPHY ARCHIVE  •  SINCE 2025</div>
      <div class="footer-line-sub">OLYMPUS OM-1  •  OLYMPUS EES-2</div>
      <div class="footer-line-sub">VOIGTLÄNDER BESSA (~1920)</div>
    </footer>
  </div>

  <!-- Fullscreen Photo Lightbox -->
  <div class="lightbox" id="lightbox" role="dialog" aria-modal="true" aria-hidden="true">
    <div class="lightbox-top">
      <button type="button" class="icon-btn" id="closeLightboxBtn" aria-label="Close full screen">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
          <path d="M19 12H5M12 19l-7-7 7-7"/>
        </svg>
      </button>

      <a class="download-pill" id="downloadBtn" href="#" download>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        <span>DOWNLOAD</span>
      </a>
    </div>

    <div class="lightbox-stage" id="lightboxStage">
      <img class="lightbox-img" id="lightboxImg" alt="" src="">
    </div>

    <div class="lightbox-bottom">
      <button type="button" class="nav-arrow prev" id="prevBtn" aria-label="Previous frame">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M15 18l-6-6 6-6"/>
        </svg>
      </button>

      <div class="lightbox-counter">
        <span id="lbIndexText">1 / {len(sorted_frames)}</span>
      </div>

      <button type="button" class="nav-arrow next" id="nextBtn" aria-label="Next frame">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9 18l6-6-6-6"/>
        </svg>
      </button>
    </div>
  </div>

<script>
  const FRAMES = {frames_json};

  // 1. Interactive shoot date pill toggle (matches RollMetadataHeader.kt)
  const datePill = document.getElementById('datePill');
  let dateTimer = null;
  let showingExact = false;
  if (datePill) {{
    datePill.addEventListener('click', () => {{
      showingExact = !showingExact;
      if (dateTimer) clearTimeout(dateTimer);
      if (showingExact) {{
        datePill.textContent = datePill.dataset.exact;
        datePill.classList.add('exact');
        dateTimer = setTimeout(() => {{
          showingExact = false;
          datePill.textContent = datePill.dataset.display;
          datePill.classList.remove('exact');
        }}, 3000);
      }} else {{
        datePill.textContent = datePill.dataset.display;
        datePill.classList.remove('exact');
      }}
    }});
  }}

  // 2. Build 2-column staggered grid preserving chronological order
  const colLeft = document.getElementById('colLeft');
  const colRight = document.getElementById('colRight');

  FRAMES.forEach((frame, index) => {{
    const card = document.createElement('div');
    card.className = 'frame-card';
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.setAttribute('aria-label', 'Frame ' + frame.frameNumber);

    const img = document.createElement('img');
    img.src = frame.thumbUrl;
    img.alt = 'Frame ' + frame.frameNumber;
    img.loading = index < 6 ? 'eager' : 'lazy';
    img.decoding = 'async';
    img.addEventListener('load', () => img.classList.add('loaded'));

    card.appendChild(img);
    card.addEventListener('click', () => openLightbox(index));
    card.addEventListener('keydown', (e) => {{
      if (e.key === 'Enter' || e.key === ' ') {{
        e.preventDefault();
        openLightbox(index);
      }}
    }});

    if (index % 2 === 0) {{
      colLeft.appendChild(card);
    }} else {{
      colRight.appendChild(card);
    }}
  }});

  // 3. Fullscreen Lightbox Controller
  const lightbox = document.getElementById('lightbox');
  const lightboxImg = document.getElementById('lightboxImg');
  const lbIndexText = document.getElementById('lbIndexText');
  const downloadBtn = document.getElementById('downloadBtn');
  const closeBtn = document.getElementById('closeLightboxBtn');
  const prevBtn = document.getElementById('prevBtn');
  const nextBtn = document.getElementById('nextBtn');
  const stage = document.getElementById('lightboxStage');

  let activeIndex = -1;

  function renderLightboxFrame() {{
    if (activeIndex < 0 || activeIndex >= FRAMES.length) return;
    const item = FRAMES[activeIndex];
    lbIndexText.textContent = (activeIndex + 1) + ' / ' + FRAMES.length;

    // Show thumbnail immediately if cached, then swap/load full-res
    lightboxImg.src = item.fullUrl;
    lightboxImg.alt = 'Frame ' + item.frameNumber;
    downloadBtn.href = item.fullUrl;
    downloadBtn.setAttribute('download', item.downloadName);

    prevBtn.style.visibility = activeIndex > 0 ? 'visible' : 'hidden';
    nextBtn.style.visibility = activeIndex < FRAMES.length - 1 ? 'visible' : 'hidden';

    // Preload neighbors
    if (activeIndex + 1 < FRAMES.length) {{
      const nextPreload = new Image();
      nextPreload.src = FRAMES[activeIndex + 1].fullUrl;
    }}
    if (activeIndex - 1 >= 0) {{
      const prevPreload = new Image();
      prevPreload.src = FRAMES[activeIndex - 1].fullUrl;
    }}
  }}

  function openLightbox(index) {{
    activeIndex = index;
    renderLightboxFrame();
    lightbox.classList.add('open');
    lightbox.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
  }}

  function closeLightbox() {{
    lightbox.classList.remove('open');
    lightbox.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    setTimeout(() => {{
      if (!lightbox.classList.contains('open')) {{
        lightboxImg.src = '';
      }}
    }}, 220);
  }}

  function stepFrame(delta) {{
    const nextIdx = activeIndex + delta;
    if (nextIdx >= 0 && nextIdx < FRAMES.length) {{
      activeIndex = nextIdx;
      renderLightboxFrame();
    }}
  }}

  closeBtn.addEventListener('click', closeLightbox);
  prevBtn.addEventListener('click', (e) => {{ e.stopPropagation(); stepFrame(-1); }});
  nextBtn.addEventListener('click', (e) => {{ e.stopPropagation(); stepFrame(1); }});
  stage.addEventListener('click', (e) => {{
    if (e.target === stage) closeLightbox();
  }});

  window.addEventListener('keydown', (e) => {{
    if (!lightbox.classList.contains('open')) return;
    if (e.key === 'Escape') closeLightbox();
    else if (e.key === 'ArrowLeft') stepFrame(-1);
    else if (e.key === 'ArrowRight') stepFrame(1);
  }});

  // Touch swipe navigation in fullscreen
  let touchStartX = 0;
  let touchStartY = 0;
  stage.addEventListener('touchstart', (e) => {{
    if (e.touches.length === 1) {{
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
    }}
  }}, {{ passive: true }});

  stage.addEventListener('touchend', (e) => {{
    if (e.changedTouches.length === 1) {{
      const dx = e.changedTouches[0].clientX - touchStartX;
      const dy = e.changedTouches[0].clientY - touchStartY;
      if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy)) {{
        if (dx < 0) stepFrame(1);
        else stepFrame(-1);
      }} else if (dy > 90 && Math.abs(dy) > Math.abs(dx)) {{
        closeLightbox();
      }}
    }}
  }}, {{ passive: true }});
</script>
</body>
</html>"""


def _find_roll_by_share_code(db: Session, share_code: str) -> Roll | None:
    normalized = share_code.strip().lower()
    if not normalized:
        return None
    stmt = select(Roll).options(selectinload(Roll.frames))
    rolls = db.scalars(stmt).all()
    for roll in rolls:
        expected = compute_share_code(roll)
        if hmac.compare_digest(expected, normalized):
            return roll
    return None


@router.get("/s/{share_code}", response_class=HTMLResponse)
def view_shared_roll_prefixed(
    share_code: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    roll = _find_roll_by_share_code(db, share_code)
    if roll is None:
        return HTMLResponse(
            content=_render_not_found_html(),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return HTMLResponse(content=_render_roll_share_html(request, roll))


@router.get("/{share_code}", response_class=HTMLResponse, include_in_schema=False)
def view_shared_roll_short(
    share_code: str,
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    roll = _find_roll_by_share_code(db, share_code)
    if roll is None:
        return HTMLResponse(
            content=_render_not_found_html(),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return HTMLResponse(content=_render_roll_share_html(request, roll))
