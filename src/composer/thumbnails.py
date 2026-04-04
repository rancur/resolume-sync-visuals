"""
Thumbnail contact sheet generator.
Creates a grid image showing all keyframes organized by phrase type.

Layout:
  - Header: track name, BPM, total duration
  - Rows: one per phrase type (drop, buildup, breakdown, intro/outro)
  - Columns: instances of that phrase type
  - Each cell: first frame thumbnail + labels (time offset, energy level)

Output: A single PNG image.
"""
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Row ordering (top to bottom)
PHRASE_ROW_ORDER = ["drop", "buildup", "breakdown", "intro", "outro"]

# Colors for phrase type labels
PHRASE_COLORS = {
    "drop": (255, 60, 60),
    "buildup": (255, 180, 40),
    "breakdown": (60, 140, 255),
    "intro": (100, 210, 100),
    "outro": (170, 130, 210),
}

DEFAULT_THUMB_SIZE = 200
HEADER_HEIGHT = 60
ROW_LABEL_WIDTH = 130
LABEL_HEIGHT = 36
PADDING = 8
BG_COLOR = (26, 26, 46)
TEXT_COLOR = (220, 220, 220)
LABEL_BG = (40, 40, 55)


def create_thumbnail_grid(
    clips: list[dict],
    analysis: dict,
    output_path: str | Path,
    config: dict | None = None,
) -> Path:
    """
    Generate a contact sheet with first frames from all clips, organized by phrase type.

    Args:
        clips: List of clip dicts (with 'path'/'file', 'label', 'start'/'start_time',
               'energy', 'phrase_idx')
        analysis: Track analysis dict (with 'title', 'bpm', 'duration', 'phrases')
        output_path: Where to save the PNG
        config: Optional config dict. Supported keys:
                - 'thumb_size': int, default 200

    Returns:
        Path to the created PNG
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    thumb_size = (config or {}).get("thumb_size", DEFAULT_THUMB_SIZE)

    # Extract first frame from each clip and collect metadata
    clip_frames = []
    for clip in clips:
        clip_path = Path(clip.get("path", clip.get("file", "")))
        label = clip.get("label", "unknown")
        start = clip.get("start", clip.get("start_time", 0))
        energy = clip.get("energy", 0)
        phrase_idx = clip.get("phrase_idx", None)

        # Pull energy from analysis phrases if not on clip
        if energy == 0 and analysis.get("phrases") and phrase_idx is not None:
            if phrase_idx < len(analysis["phrases"]):
                energy = analysis["phrases"][phrase_idx].get("energy", 0)

        frame = _extract_first_frame(clip_path, thumb_size)
        clip_frames.append({
            "label": label,
            "start": start,
            "energy": energy,
            "frame": frame,
            "phrase_idx": phrase_idx if phrase_idx is not None else 0,
        })

    if not clip_frames:
        logger.warning("No clip frames for thumbnail grid")
        img = Image.new("RGB", (400, 120), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw.text((20, 40), "No clips found", fill=TEXT_COLOR)
        img.save(str(output_path), "PNG")
        return output_path

    # Group clips by phrase type
    grouped: dict[str, list] = {}
    for cf in clip_frames:
        grouped.setdefault(cf["label"], []).append(cf)

    # Determine row order: standard order first, then any extras
    row_types = [pt for pt in PHRASE_ROW_ORDER if pt in grouped]
    for label in grouped:
        if label not in row_types:
            row_types.append(label)

    max_cols = max(len(grouped[rt]) for rt in row_types) if row_types else 1
    n_rows = len(row_types)

    # Calculate canvas size
    cell_w = thumb_size + PADDING
    cell_h = thumb_size + LABEL_HEIGHT + PADDING
    grid_w = ROW_LABEL_WIDTH + max_cols * cell_w + PADDING
    grid_h = HEADER_HEIGHT + n_rows * cell_h + PADDING

    canvas = Image.new("RGB", (grid_w, grid_h), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    font = _get_font(14)
    font_small = _get_font(11)
    font_header = _get_font(18)

    # -- Header --
    track_name = analysis.get("title", "Unknown Track")
    bpm = analysis.get("bpm", 0)
    duration = analysis.get("duration", 0)
    total_clips = len(clips)
    header_text = f"{track_name}  |  {bpm:.0f} BPM  |  {duration:.0f}s  |  {total_clips} clips"
    draw.text((PADDING, PADDING + 4), header_text, fill=TEXT_COLOR, font=font_header)
    draw.line(
        [(PADDING, HEADER_HEIGHT - 4), (grid_w - PADDING, HEADER_HEIGHT - 4)],
        fill=(80, 80, 100), width=1,
    )

    # -- Rows --
    for row_idx, phrase_type in enumerate(row_types):
        y_base = HEADER_HEIGHT + row_idx * cell_h
        label_color = PHRASE_COLORS.get(phrase_type, (180, 180, 180))

        # Row label area
        draw.rectangle(
            [PADDING, y_base + PADDING, ROW_LABEL_WIDTH - 4, y_base + thumb_size + PADDING],
            fill=LABEL_BG,
        )
        # Color accent bar
        draw.rectangle(
            [PADDING, y_base + PADDING, PADDING + 4, y_base + thumb_size + PADDING],
            fill=label_color,
        )
        draw.text(
            (PADDING + 12, y_base + PADDING + 10),
            phrase_type.upper(),
            fill=label_color,
            font=font,
        )
        count = len(grouped[phrase_type])
        draw.text(
            (PADDING + 12, y_base + PADDING + 30),
            f"{count} clip{'s' if count != 1 else ''}",
            fill=(140, 140, 160),
            font=font_small,
        )

        # -- Cells --
        for col_idx, cf in enumerate(grouped[phrase_type]):
            x_base = ROW_LABEL_WIDTH + col_idx * cell_w

            # Thumbnail
            if cf["frame"] is not None:
                frame_img = _fit_thumbnail(cf["frame"], thumb_size)
                canvas.paste(frame_img, (x_base, y_base + PADDING))
            else:
                draw.rectangle(
                    [x_base, y_base + PADDING,
                     x_base + thumb_size, y_base + thumb_size + PADDING],
                    fill=(60, 60, 70),
                )
                draw.text(
                    (x_base + thumb_size // 4, y_base + thumb_size // 2),
                    "No frame",
                    fill=(120, 120, 130),
                    font=font_small,
                )

            # Info label below thumbnail
            time_str = _format_time(cf["start"])
            energy_val = cf["energy"]
            energy_bar = _energy_bar(energy_val)
            info_text = f"{time_str}  E:{energy_bar}"

            draw.rectangle(
                [x_base, y_base + thumb_size + PADDING,
                 x_base + thumb_size, y_base + cell_h - 2],
                fill=LABEL_BG,
            )
            draw.text(
                (x_base + 4, y_base + thumb_size + PADDING + 4),
                info_text,
                fill=TEXT_COLOR,
                font=font_small,
            )

    canvas.save(str(output_path), "PNG")
    logger.info(f"Thumbnail grid created: {output_path} ({grid_w}x{grid_h})")
    return output_path


def _extract_first_frame(clip_path: Path, thumb_size: int) -> Optional[Image.Image]:
    """Extract the first frame from a video file using ffmpeg."""
    if not clip_path.exists():
        logger.debug(f"Clip not found for thumbnail: {clip_path}")
        return None

    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-vframes", "1",
            "-vf", f"scale={thumb_size}:-1",
            "-f", "image2",
            tmp_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        tmp_file = Path(tmp_path)
        if result.returncode == 0 and tmp_file.exists() and tmp_file.stat().st_size > 0:
            img = Image.open(tmp_path).convert("RGB")
            tmp_file.unlink(missing_ok=True)
            return img
        else:
            tmp_file.unlink(missing_ok=True)
            return None
    except Exception as e:
        logger.debug(f"Failed to extract frame from {clip_path}: {e}")
        return None


def _fit_thumbnail(img: Image.Image, size: int) -> Image.Image:
    """Fit image into a square thumbnail, center-cropping the longer side."""
    w, h = img.size
    if w == size and h == size:
        return img

    # Scale so shorter side = size
    if w > h:
        new_h = size
        new_w = int(w * size / h)
    else:
        new_w = size
        new_h = int(h * size / w)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Center crop to square
    left = (new_w - size) // 2
    top = (new_h - size) // 2
    return img.crop((left, top, left + size, top + size))


def _format_time(seconds: float) -> str:
    """Format seconds as M:SS."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


def _energy_bar(energy: float) -> str:
    """Compact text energy indicator."""
    filled = int(energy * 5)
    return "|" * filled + "." * (5 - filled)


def _get_font(size: int = 14):
    """Try to load a TTF font, falling back to PIL default."""
    for path in [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()
