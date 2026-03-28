"""
Resolume Arena show composition builder.

Creates a single .avc composition file for an entire DJ set / library.
Each track's clips become columns in shared layers, organized by phrase type.

Structure:
  Composition "Will See"
    └── Deck "Show"
        ├── Layer "Drops"      → [Track1_drop1, Track1_drop2, Track2_drop1, ...]
        ├── Layer "Buildups"   → [Track1_buildup1, Track2_buildup1, ...]
        ├── Layer "Breakdowns" → [Track1_breakdown1, Track2_breakdown1, ...]
        └── Layer "Ambient"    → [Track1_intro1, Track2_intro1, ...]

The VJ triggers columns to play clips across all layers simultaneously.
Each clip has BPM Sync transport set to the track's analyzed BPM.
"""
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from xml.dom import minidom

from .export import LAYER_CONFIG, _LABEL_TO_LAYER

logger = logging.getLogger(__name__)


def create_show_composition(
    tracks: list[dict],
    output_path: str | Path,
    show_name: str = "Will See",
    clip_base_path: Optional[Path] = None,
) -> Path:
    """
    Create a single Resolume .avc composition for multiple tracks.

    Each track's loops/clips are added as columns across the shared layers.
    Clips are grouped by phrase type into the appropriate layer.

    Args:
        tracks: List of track composition dicts. Each should have:
            - track: str (track name)
            - bpm: float
            - loops: list[dict] with file, label, beats, duration
            - clips: list[dict] (fallback if no loops)
        output_path: Where to save the .avc file
        show_name: Name of the composition (default: "Will See")
        clip_base_path: Optional base path for relative clip references

    Returns:
        Path to the .avc file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not tracks:
        raise ValueError("No tracks provided")

    # Use first track BPM as default master tempo
    master_bpm = tracks[0].get("bpm", 128.0)

    arena = ET.Element("Arena")
    composition = ET.SubElement(arena, "Composition", name=show_name)
    ET.SubElement(composition, "Tempo", bpm=f"{master_bpm:.1f}")

    # Single deck for the whole show
    deck = ET.SubElement(composition, "Deck", name=show_name)

    # Collect all clips across all tracks, organized by layer
    layer_clips = {n: [] for n in LAYER_CONFIG}

    for track_data in tracks:
        track_name = track_data.get("track", "Unknown")
        track_bpm = track_data.get("bpm", 128.0)

        # Use loops if available, fall back to clips
        source_clips = track_data.get("loops", [])
        if not source_clips:
            source_clips = track_data.get("clips", [])

        for clip in source_clips:
            label = clip.get("label", "intro")
            layer_num = _LABEL_TO_LAYER.get(label, 4)

            clip_path = clip.get("file", clip.get("path", ""))
            if clip_base_path and clip_path:
                try:
                    clip_path = str(Path(clip_path).relative_to(clip_base_path))
                except ValueError:
                    pass

            layer_clips[layer_num].append({
                "path": clip_path,
                "label": label,
                "beats": clip.get("beats", 16),
                "bpm": track_bpm,
                "track_name": track_name,
                "duration": clip.get("duration", 0),
            })

    # Build layers
    total_clips = 0
    for layer_num in sorted(LAYER_CONFIG.keys()):
        cfg = LAYER_CONFIG[layer_num]
        clips = layer_clips.get(layer_num, [])

        layer_elem = ET.SubElement(
            deck, "Layer",
            name=cfg["name"],
            blendMode=cfg["blend_mode"],
            opacity=str(cfg["opacity"]),
        )

        for idx, clip in enumerate(clips):
            clip_name = f"{clip['track_name']} - {clip['label']}_{idx + 1:03d}"
            # Truncate long names
            if len(clip_name) > 60:
                clip_name = clip_name[:57] + "..."

            clip_elem = ET.SubElement(
                layer_elem, "Clip",
                name=clip_name,
                transport="BPMSync",
                beats=str(clip["beats"]),
                bpm=f"{clip['bpm']:.1f}",
            )
            ET.SubElement(clip_elem, "Source", path=clip["path"])
            ET.SubElement(clip_elem, "Video", width="1920", height="1080")
            total_clips += 1

    # Write XML
    xml_str = _prettify_xml(arena)
    output_path.write_text(xml_str, encoding="utf-8")

    n_tracks = len(tracks)
    logger.info(f"Show composition '{show_name}': {n_tracks} tracks, {total_clips} clips → {output_path}")
    return output_path


def build_show_from_output_dir(
    output_base: str | Path,
    show_path: str | Path,
    show_name: str = "Will See",
    clip_base_path: Optional[Path] = None,
) -> Path:
    """
    Scan an output directory for all generated tracks and build a show composition.

    Looks for metadata.json files in each subdirectory to find track data.

    Args:
        output_base: Directory containing per-track output folders
        show_path: Where to save the .avc file
        show_name: Composition name
        clip_base_path: Base path for relative clip references

    Returns:
        Path to the .avc file
    """
    output_base = Path(output_base)
    tracks = []

    for track_dir in sorted(output_base.iterdir()):
        meta_path = track_dir / "metadata.json"
        if not meta_path.exists():
            continue

        try:
            meta = json.loads(meta_path.read_text())
            tracks.append(meta)
            logger.info(f"  Found: {meta.get('track', track_dir.name)} "
                         f"({len(meta.get('loops', []))} loops)")
        except Exception as e:
            logger.warning(f"  Skipped {track_dir.name}: {e}")

    if not tracks:
        raise ValueError(f"No tracks found in {output_base}")

    logger.info(f"Building show from {len(tracks)} tracks")
    return create_show_composition(tracks, show_path, show_name, clip_base_path)


def _prettify_xml(element: ET.Element) -> str:
    """Pretty-print XML with indentation."""
    rough = ET.tostring(element, encoding="unicode", xml_declaration=True)
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding=None)
