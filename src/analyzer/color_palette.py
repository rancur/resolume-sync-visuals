"""
Color palette extraction from album art.

Uses k-means clustering to find dominant colors, then maps them
to named color slots for use in visual generation prompts.
"""
import io
import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Approximate color name mapping for prompt injection
_COLOR_NAMES = {
    (255, 0, 0): "red",
    (0, 255, 0): "green",
    (0, 0, 255): "blue",
    (255, 255, 0): "yellow",
    (255, 165, 0): "orange",
    (128, 0, 128): "purple",
    (255, 192, 203): "pink",
    (0, 255, 255): "cyan",
    (255, 255, 255): "white",
    (0, 0, 0): "black",
    (128, 128, 128): "gray",
    (139, 69, 19): "brown",
    (0, 128, 128): "teal",
    (75, 0, 130): "indigo",
    (255, 20, 147): "hot pink",
    (0, 100, 0): "dark green",
    (220, 20, 60): "crimson",
    (64, 224, 208): "turquoise",
    (255, 215, 0): "gold",
    (192, 192, 192): "silver",
}


def extract_palette(
    image_data: bytes,
    n_colors: int = 6,
) -> list[dict]:
    """
    Extract dominant colors from image data using k-means clustering.

    Args:
        image_data: Raw bytes of an image (JPEG, PNG, etc.)
        n_colors: Number of dominant colors to extract (default 6).

    Returns:
        List of color dicts: [{"hex": "#FF0000", "rgb": [255,0,0], "name": "red", "weight": 0.35}, ...]
        Sorted by weight (most dominant first).
    """
    from PIL import Image
    from sklearn.cluster import KMeans

    img = Image.open(io.BytesIO(image_data))
    img = img.convert("RGB")

    # Resize for speed (k-means on full-res is slow)
    img.thumbnail((200, 200))
    pixels = np.array(img).reshape(-1, 3).astype(float)

    # Remove near-black and near-white (often borders/backgrounds)
    brightness = pixels.mean(axis=1)
    mask = (brightness > 15) & (brightness < 240)
    filtered = pixels[mask] if mask.sum() > n_colors * 10 else pixels

    km = KMeans(n_clusters=n_colors, n_init=3, random_state=42)
    km.fit(filtered)

    # Compute weight from cluster sizes
    labels, counts = np.unique(km.labels_, return_counts=True)
    total = counts.sum()

    palette = []
    for center, count in sorted(zip(km.cluster_centers_, counts), key=lambda x: -x[1]):
        r, g, b = int(center[0]), int(center[1]), int(center[2])
        palette.append({
            "hex": f"#{r:02X}{g:02X}{b:02X}",
            "rgb": [r, g, b],
            "name": _nearest_color_name(r, g, b),
            "weight": round(count / total, 3),
        })

    return palette


def extract_palette_from_file(
    file_path: str | Path,
    n_colors: int = 6,
) -> list[dict]:
    """Extract palette from an image file on disk."""
    data = Path(file_path).read_bytes()
    return extract_palette(data, n_colors)


def extract_palette_from_audio(
    audio_path: str | Path,
    n_colors: int = 6,
) -> Optional[list[dict]]:
    """
    Extract palette from embedded album art in an audio file.

    Uses mutagen to read embedded images from ID3/FLAC/MP4 tags.
    Returns None if no album art is found.
    """
    try:
        import mutagen
        from mutagen.id3 import ID3
        from mutagen.flac import FLAC
        from mutagen.mp4 import MP4

        audio = mutagen.File(str(audio_path))
        if audio is None:
            return None

        image_data = None

        # MP3 (ID3)
        if hasattr(audio, "tags") and audio.tags:
            for key in audio.tags:
                if key.startswith("APIC"):
                    image_data = audio.tags[key].data
                    break

        # FLAC
        if image_data is None and isinstance(audio, FLAC):
            if audio.pictures:
                image_data = audio.pictures[0].data

        # MP4/M4A
        if image_data is None and isinstance(audio, MP4):
            covers = audio.tags.get("covr", [])
            if covers:
                image_data = bytes(covers[0])

        if image_data is None:
            return None

        return extract_palette(image_data, n_colors)

    except ImportError:
        logger.warning("mutagen not installed — cannot extract album art colors")
        return None
    except Exception as e:
        logger.debug(f"Failed to extract album art from {audio_path}: {e}")
        return None


def palette_to_prompt(palette: list[dict], max_colors: int = 4) -> str:
    """
    Convert a color palette to a prompt fragment.

    Example output: "color palette: deep blue (#1A237E), crimson (#DC143C), gold (#FFD700)"
    """
    if not palette:
        return ""
    top = palette[:max_colors]
    parts = [f"{c['name']} ({c['hex']})" for c in top]
    return "color palette: " + ", ".join(parts)


def _nearest_color_name(r: int, g: int, b: int) -> str:
    """Find the closest named color."""
    min_dist = float("inf")
    best = "unknown"
    for (cr, cg, cb), name in _COLOR_NAMES.items():
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < min_dist:
            min_dist = dist
            best = name
    return best
