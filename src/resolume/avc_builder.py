"""
Resolume Arena .avc Composition Builder.

Generates .avc files that Resolume Arena 7.25+ can load correctly,
based on reverse-engineering of the actual saved format.

Key findings from Resolume-saved reference file:
- TransportType value 5 = Denon (StagelinQ)
- PhaseSourceStageLinQ with "Title or File" param matches tracks
- All Param elements need T="STRING"/"DOUBLE"/"BOOL" type attributes
- Video path appears in both PreloadData and PrimarySource
- Duration in seconds (DurationSource) and milliseconds (ValueRange max)
- Clip has layerIndex + columnIndex, lives inside Deck element
"""
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

logger = logging.getLogger(__name__)


def build_show_avc(
    tracks: list[dict],
    output_path: str | Path,
    show_name: str = "My Show",
) -> Path:
    """
    Build a Resolume .avc composition with Denon transport mode.

    Each track becomes a clip in one layer, each in its own column.
    StagelinQ auto-matches by track title.

    Args:
        tracks: List of dicts with:
            - title: str (MUST match audio ID3 title exactly)
            - video_path: str (absolute path as Resolume sees it)
            - duration: float (seconds)
            - width: int (default 1280)
            - height: int (default 720)
        output_path: Where to write the .avc file
        show_name: Composition name

    Returns:
        Path to the .avc file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_tracks = len(tracks)
    n_columns = n_tracks + 1  # Resolume always has one extra empty column
    ts = int(time.time() * 1000)

    # ── Root Composition ──
    comp = ET.Element("Composition",
        name="Composition",
        uniqueId=str(ts),
        numDecks="1",
        currentDeckIndex="0",
        numLayers="1",
        numColumns=str(n_columns),
        compositionIsRelative="0",
    )

    # Version info
    ver = ET.SubElement(comp, "versionInfo",
        name="Resolume Arena",
        majorVersion="7", minorVersion="25", microVersion="1", revision="0",
    )

    # Composition info
    info = ET.SubElement(comp, "CompositionInfo",
        name=show_name,
        description=f"Denon show: {n_tracks} tracks",
        width="1920", height="1080",
    )
    ET.SubElement(info, "DeckInfo",
        name=show_name, id=str(ts + 1), closed="0",
    )

    # Composition params
    params = ET.SubElement(comp, "Params", name="Params")
    _param_string(params, "Name", show_name)
    _param_string(params, "Description", f"Denon show: {n_tracks} tracks")

    # Audio/Video tracks (composition level)
    audio = ET.SubElement(comp, "AudioTrack", name="AudioTrack")
    ET.SubElement(audio, "AudioEffectChain", name="AudioEffectChain")

    video = ET.SubElement(comp, "VideoTrack", name="VideoTrack")
    vparams = ET.SubElement(video, "Params", name="Params")
    _param_range(vparams, "Width", 1920)
    _param_range(vparams, "Height", 1080)

    # ── Layer ──
    layer = ET.SubElement(comp, "Layer",
        name="Layer",
        uniqueId=str(ts + 10),
        layerIndex="0",
    )
    lparams = ET.SubElement(layer, "Params", name="Params")
    _param_string(lparams, "Name", "Denon Visuals")

    # Layer audio/video tracks
    laudio = ET.SubElement(layer, "AudioTrack", name="AudioTrack")
    ET.SubElement(laudio, "AudioEffectChain", name="AudioEffectChain")

    lvideo = ET.SubElement(layer, "VideoTrack", name="VideoTrack")
    lvparams = ET.SubElement(lvideo, "Params", name="Params")
    _param_range(lvparams, "Opacity", 1.0)
    _param_range(lvparams, "Width", 1920)
    _param_range(lvparams, "Height", 1080)

    # ── Tempo Controller ──
    ET.SubElement(comp, "TempoController", name="TempoController")

    # ── Deck ──
    deck = ET.SubElement(comp, "Deck",
        name="Deck",
        uniqueId=str(ts + 1),
        closed="0",
        numLayersWithContent="1",
        numColumnsWithContent=str(n_tracks),
        numLayers="1",
        numColumns=str(n_columns),
        deckIndex="0",
    )
    dparams = ET.SubElement(deck, "Params", name="Params")
    _param_string(dparams, "Name", show_name)

    # ── Columns ──
    for i, track in enumerate(tracks):
        col = ET.SubElement(deck, "Column",
            uniqueId=str(ts + 100 + i),
            columnIndex=str(i),
        )
        cparams = ET.SubElement(col, "Params", name="Params")
        _param_string(cparams, "Name", track["title"], default="Column #")

    # Extra empty column (Resolume always has one)
    ET.SubElement(deck, "Column",
        uniqueId=str(ts + 100 + n_tracks),
        columnIndex=str(n_tracks),
    )

    # ── Clips ──
    for i, track in enumerate(tracks):
        title = track["title"]
        video_path = track["video_path"]
        duration_s = track.get("duration", 300.0)
        duration_ms = int(duration_s * 1000)
        width = track.get("width", 1280)
        height = track.get("height", 720)

        clip = ET.SubElement(deck, "Clip",
            name="Clip",
            uniqueId=str(ts + 200 + i),
            layerIndex="0",
            columnIndex=str(i),
        )

        # Preload data
        preload = ET.SubElement(clip, "PreloadData")
        ET.SubElement(preload, "VideoFile", value=video_path)

        # Clip params
        cparams = ET.SubElement(clip, "Params", name="Params")
        _param_string(cparams, "Name", title, default=title)
        # TransportType 5 = Denon
        ET.SubElement(cparams, "ParamChoice",
            name="TransportType", default="0", value="5", storeChoices="0",
        )

        # Transport with StagelinQ
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
        _param_string(slparams, "Title or File", title)
        ET.SubElement(position, "ValueRange",
            name="minMax", min="0", max=str(duration_ms),
        )

        # Video track
        cvideo = ET.SubElement(clip, "VideoTrack", name="VideoTrack")
        cvparams = ET.SubElement(cvideo, "Params", name="Params")
        _param_range(cvparams, "Width", width)
        _param_range(cvparams, "Height", height)

        # Primary source
        psource = ET.SubElement(cvideo, "PrimarySource")
        vsource = ET.SubElement(psource, "VideoSource",
            name="VideoSource",
            width=str(width), height=str(height),
            type="VideoFormatReaderSource",
        )
        ET.SubElement(vsource, "VideoFormatReaderSource",
            fileName=video_path,
        )

    # Extra empty clip for the empty column
    ET.SubElement(deck, "Clip",
        name="Clip",
        uniqueId=str(ts + 200 + n_tracks),
        layerIndex="0",
        columnIndex=str(n_tracks),
    )

    # ── Write ──
    xml_str = _prettify(comp)
    output_path.write_text(xml_str, encoding="utf-8")

    logger.info(f"Built .avc: {show_name} — {n_tracks} tracks → {output_path}")
    return output_path


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
    # Remove extra blank lines
    return "\n".join(line for line in lines if line.strip())
