"""
Resolume Arena Advanced Video Composition (.avc) file generator.

Generates XML-based .avc files that can be loaded directly into Resolume Arena.
The composition format organizes clips into layers/decks with transport settings.

Resolume Arena Concepts:
- Composition: Top-level project
- Deck: A bank of layers+columns
- Layer: Stacked vertically, blended together
- Clip: Individual video file with transport settings
- Transport: BPM Sync ties clip playback to the master clock
"""
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from xml.dom import minidom

from .export import LAYER_CONFIG, _LABEL_TO_LAYER

logger = logging.getLogger(__name__)


def create_composition(
    composition_data: dict,
    output_path: Path,
    clip_base_path: Optional[Path] = None,
) -> Path:
    """Generate a Resolume Arena .avc composition file.

    Uses the composition metadata (from compose_timeline) to build
    the XML with proper layer/clip/transport settings.

    Args:
        composition_data: Composition metadata dict from compose_timeline().
            Expected keys: track, bpm, time_signature, duration, loops/clips,
            and optionally resolume_mapping.
        output_path: Where to write the .avc file.
        clip_base_path: Optional base path for clip file references.
            If provided, clip paths are made relative to this directory.
            If None, absolute paths are used.

    Returns:
        Path to the generated .avc file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bpm = composition_data.get("bpm", 120.0)
    track_name = composition_data.get("track", "Untitled")
    time_sig = composition_data.get("time_signature", 4)

    # Build the XML tree
    arena = ET.Element("Arena")
    composition = ET.SubElement(arena, "Composition", name=track_name)

    # Tempo element
    ET.SubElement(composition, "Tempo", bpm=f"{bpm:.1f}")

    # Create a single deck
    deck = ET.SubElement(composition, "Deck", name=track_name)

    # Organize clips into layers
    layer_clips = _organize_clips_by_layer(composition_data)

    # Build each layer
    for layer_num in sorted(LAYER_CONFIG.keys()):
        layer_cfg = LAYER_CONFIG[layer_num]
        clips = layer_clips.get(layer_num, [])

        layer_elem = ET.SubElement(
            deck, "Layer",
            name=layer_cfg["name"],
            blendMode=layer_cfg["blend_mode"],
            opacity=str(layer_cfg["opacity"]),
        )

        for idx, clip in enumerate(clips):
            clip_path = clip.get("file", "")
            if clip_base_path and clip_path:
                try:
                    clip_path = str(Path(clip_path).relative_to(clip_base_path))
                except ValueError:
                    pass  # Keep absolute if not relative-able

            label = clip.get("label", "clip")
            clip_name = f"{label}_{idx + 1:03d}"
            beats = clip.get("beats", 16)

            clip_elem = ET.SubElement(
                layer_elem, "Clip",
                name=clip_name,
                transport="BPMSync",
                beats=str(beats),
            )
            ET.SubElement(clip_elem, "Source", path=clip_path)

            # Video dimensions -- use clip metadata or defaults
            width = clip.get("width", 1920)
            height = clip.get("height", 1080)
            ET.SubElement(
                clip_elem, "Video",
                width=str(width), height=str(height),
            )

    # Write the XML
    xml_str = _prettify_xml(arena)
    output_path.write_text(xml_str, encoding="utf-8")

    logger.info(f"Composition written to {output_path}")
    return output_path


def create_multi_track_composition(
    tracks: list[dict],
    output_path: Path,
) -> Path:
    """Create a composition with multiple tracks as decks.

    Each track becomes its own deck in the composition, allowing
    the VJ to switch between tracks (songs) during a set.

    Args:
        tracks: List of composition data dicts (one per track).
            Each should have: track, bpm, duration, loops/clips.
        output_path: Where to write the .avc file.

    Returns:
        Path to the generated .avc file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not tracks:
        raise ValueError("No tracks provided for multi-track composition")

    # Use the first track's BPM as the master tempo (VJ can override)
    master_bpm = tracks[0].get("bpm", 120.0)

    arena = ET.Element("Arena")
    composition = ET.SubElement(arena, "Composition", name="Multi-Track Set")

    ET.SubElement(composition, "Tempo", bpm=f"{master_bpm:.1f}")

    for track_data in tracks:
        track_name = track_data.get("track", "Untitled")
        deck = ET.SubElement(composition, "Deck", name=track_name)

        layer_clips = _organize_clips_by_layer(track_data)

        for layer_num in sorted(LAYER_CONFIG.keys()):
            layer_cfg = LAYER_CONFIG[layer_num]
            clips = layer_clips.get(layer_num, [])

            layer_elem = ET.SubElement(
                deck, "Layer",
                name=layer_cfg["name"],
                blendMode=layer_cfg["blend_mode"],
                opacity=str(layer_cfg["opacity"]),
            )

            for idx, clip in enumerate(clips):
                clip_path = clip.get("file", "")
                label = clip.get("label", "clip")
                clip_name = f"{label}_{idx + 1:03d}"
                beats = clip.get("beats", 16)

                clip_elem = ET.SubElement(
                    layer_elem, "Clip",
                    name=clip_name,
                    transport="BPMSync",
                    beats=str(beats),
                )
                ET.SubElement(clip_elem, "Source", path=clip_path)

                width = clip.get("width", 1920)
                height = clip.get("height", 1080)
                ET.SubElement(
                    clip_elem, "Video",
                    width=str(width), height=str(height),
                )

    xml_str = _prettify_xml(arena)
    output_path.write_text(xml_str, encoding="utf-8")

    logger.info(f"Multi-track composition written to {output_path} ({len(tracks)} tracks)")
    return output_path


def _organize_clips_by_layer(composition_data: dict) -> dict:
    """Sort clips from a composition into layer buckets.

    Returns dict mapping layer_num -> list of clip dicts.
    """
    layer_clips = {n: [] for n in LAYER_CONFIG}

    # Prefer loops (seamless), fall back to raw clips
    source = composition_data.get("loops", [])
    if not source:
        source = composition_data.get("clips", [])

    for clip in source:
        label = clip.get("label", "intro")
        layer_num = _LABEL_TO_LAYER.get(label, 4)
        layer_clips[layer_num].append(clip)

    return layer_clips


def _prettify_xml(elem: ET.Element) -> str:
    """Return a pretty-printed XML string with declaration."""
    rough = ET.tostring(elem, encoding="unicode", xml_declaration=False)
    parsed = minidom.parseString(rough)
    pretty = parsed.toprettyxml(indent="  ", encoding=None)
    # Remove extra blank lines that minidom adds
    lines = [line for line in pretty.split("\n") if line.strip()]
    return "\n".join(lines) + "\n"
