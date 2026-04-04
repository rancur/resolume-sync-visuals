"""
Multi-layer Resolume composition builder.
Issue #41: Multi-layer Resolume compositions (background + foreground + overlay).

Generates 3-layer compositions where:
- Background: slow-moving atmospheric visuals (lower res, cheaper)
- Foreground: beat-synced high-energy brand visuals
- Overlay: procedural effects, text, particles (no AI cost)
"""
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from xml.dom import minidom

logger = logging.getLogger(__name__)

# Layer definitions
MULTI_LAYER_CONFIG = {
    "background": {
        "name": "Background",
        "description": "Slow-moving atmospheric textures",
        "blend_mode": "Normal",
        "opacity": 1.0,
        "quality": "draft",  # Lower quality = cheaper
        "resolution_scale": 0.5,  # Half resolution
        "layer_index": 0,
    },
    "foreground": {
        "name": "Foreground",
        "description": "Beat-synced, high-energy brand visuals",
        "blend_mode": "Screen",
        "opacity": 0.9,
        "quality": "high",
        "resolution_scale": 1.0,
        "layer_index": 1,
    },
    "overlay": {
        "name": "Overlay",
        "description": "Effects, text, particles (procedural)",
        "blend_mode": "Add",
        "opacity": 0.7,
        "quality": "procedural",  # No AI cost
        "resolution_scale": 1.0,
        "layer_index": 2,
    },
}


def build_multilayer_avc(
    tracks: list[dict],
    output_path: str | Path,
    show_name: str = "My Show",
    layer_config: Optional[dict] = None,
) -> Path:
    """
    Build a multi-layer Resolume .avc composition.

    Each track gets clips on 3 layers (bg/fg/overlay), with appropriate
    blend modes and quality settings.

    Args:
        tracks: List of dicts with:
            - title: str
            - video_path: str (foreground video)
            - bg_video_path: str (optional background video)
            - overlay_path: str (optional overlay video)
            - duration: float (seconds)
        output_path: Where to write the .avc
        show_name: Composition name
        layer_config: Optional override for layer settings

    Returns:
        Path to the .avc file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    config = layer_config or MULTI_LAYER_CONFIG
    n_tracks = len(tracks)
    n_columns = n_tracks + 1
    ts = int(time.time() * 1000)

    # Root composition
    comp = ET.Element("Composition",
        name="Composition",
        uniqueId=str(ts),
        numDecks="1",
        currentDeckIndex="0",
        numLayers=str(len(config)),
        numColumns=str(n_columns),
    )

    # Version
    ET.SubElement(comp, "versionInfo",
        name="Resolume Arena",
        majorVersion="7", minorVersion="25", microVersion="1", revision="0",
    )

    # Composition info
    info = ET.SubElement(comp, "CompositionInfo",
        name=show_name,
        description=f"Multi-layer composition: {n_tracks} tracks",
        width="1920", height="1080",
    )

    # Create layers
    for layer_key, lcfg in config.items():
        layer = ET.SubElement(comp, "Layer",
            name="Layer",
            uniqueId=str(ts + 10 + lcfg["layer_index"]),
            layerIndex=str(lcfg["layer_index"]),
        )
        lparams = ET.SubElement(layer, "Params", name="Params")
        _param_string(lparams, "Name", lcfg["name"])

        # Blend mode
        _param_string(lparams, "BlendMode", lcfg["blend_mode"])

        # Opacity
        lvideo = ET.SubElement(layer, "VideoTrack", name="VideoTrack")
        lvparams = ET.SubElement(lvideo, "Params", name="Params")
        _param_range(lvparams, "Opacity", lcfg["opacity"])

    # Deck
    deck = ET.SubElement(comp, "Deck",
        name="Deck",
        uniqueId=str(ts + 1),
        numLayersWithContent=str(len(config)),
        numColumnsWithContent=str(n_tracks),
        numLayers=str(len(config)),
        numColumns=str(n_columns),
        deckIndex="0",
    )
    dparams = ET.SubElement(deck, "Params", name="Params")
    _param_string(dparams, "Name", show_name)

    # Columns
    for i, track in enumerate(tracks):
        col = ET.SubElement(deck, "Column",
            uniqueId=str(ts + 100 + i),
            columnIndex=str(i),
        )
        cparams = ET.SubElement(col, "Params", name="Params")
        _param_string(cparams, "Name", track.get("title", f"Track {i+1}"))

    # Clips - one per layer per track
    for i, track in enumerate(tracks):
        title = track.get("title", f"Track {i+1}")
        duration_s = track.get("duration", 300.0)

        # Foreground clip (main video)
        fg_path = track.get("video_path", "")
        if fg_path:
            _add_clip(deck, ts, i, 1, title, fg_path, duration_s)

        # Background clip
        bg_path = track.get("bg_video_path", fg_path)  # Fall back to fg
        if bg_path:
            _add_clip(deck, ts + 1000, i, 0, f"{title} BG", bg_path, duration_s)

        # Overlay clip
        overlay_path = track.get("overlay_path", "")
        if overlay_path:
            _add_clip(deck, ts + 2000, i, 2, f"{title} OVR", overlay_path, duration_s)

    # Write
    xml_str = _prettify(comp)
    output_path.write_text(xml_str, encoding="utf-8")

    logger.info(f"Built multi-layer .avc: {show_name} -- {n_tracks} tracks x {len(config)} layers -> {output_path}")
    return output_path


def get_layer_config() -> dict:
    """Return the current multi-layer configuration."""
    return MULTI_LAYER_CONFIG.copy()


def estimate_multilayer_cost(
    n_tracks: int,
    avg_cost_per_track: float = 0.05,
) -> dict:
    """Estimate cost for multi-layer generation vs single-layer."""
    single_cost = n_tracks * avg_cost_per_track
    # Background at 50% (lower res), overlay is free (procedural)
    multi_cost = n_tracks * (avg_cost_per_track * 1.0 + avg_cost_per_track * 0.5)
    return {
        "single_layer_cost": round(single_cost, 4),
        "multi_layer_cost": round(multi_cost, 4),
        "cost_increase": round(multi_cost / single_cost if single_cost > 0 else 0, 2),
        "overlay_cost": 0.0,  # Procedural, no AI cost
        "note": "Background generated at half resolution. Overlay is procedural (free).",
    }


def _add_clip(deck, ts_base, col_idx, layer_idx, name, video_path, duration_s):
    """Add a clip element to the deck."""
    clip = ET.SubElement(deck, "Clip",
        name="Clip",
        uniqueId=str(ts_base + 200 + col_idx * 10 + layer_idx),
        layerIndex=str(layer_idx),
        columnIndex=str(col_idx),
    )

    preload = ET.SubElement(clip, "PreloadData")
    ET.SubElement(preload, "VideoFile", value=video_path)

    cparams = ET.SubElement(clip, "Params", name="Params")
    _param_string(cparams, "Name", name)
    ET.SubElement(cparams, "ParamChoice",
        name="TransportType", default="0", value="5",
    )

    transport = ET.SubElement(clip, "Transport", name="Transport")
    tparams = ET.SubElement(transport, "Params", name="Params")
    position = ET.SubElement(tparams, "ParamRange",
        name="Position", T="DOUBLE", default="0", value="0",
    )
    ET.SubElement(position, "DurationSource",
        defaultDuration=f"{duration_s}s",
    )
    stagelinq = ET.SubElement(position, "PhaseSourceStageLinQ",
        name="PhaseSourceStageLinQ", phase="0",
    )
    slparams = ET.SubElement(stagelinq, "Params", name="Params")
    _param_string(slparams, "Title or File", name)


def _param_string(parent, name, value, default=""):
    ET.SubElement(parent, "Param",
        name=name, T="STRING", default=default, value=value,
    )


def _param_range(parent, name, value, default=None):
    if default is None:
        default = value
    pr = ET.SubElement(parent, "ParamRange",
        name=name, T="DOUBLE",
        default=str(default), value=str(value),
    )
    ET.SubElement(pr, "PhaseSourceStatic", name="PhaseSourceStatic")
    return pr


def _prettify(element):
    rough = ET.tostring(element, encoding="unicode", xml_declaration=True)
    parsed = minidom.parseString(rough)
    lines = parsed.toprettyxml(indent="\t", encoding=None).split("\n")
    return "\n".join(line for line in lines if line.strip())
