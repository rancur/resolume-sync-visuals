"""
Resolume Arena show composition builder.

Creates .avc composition files for DJ sets / libraries.

Two modes:
1. BPM Sync mode: phrase-based clips across shared layers (original)
2. Denon transport mode: one full-song video per clip, linked to Denon
   decks by track title for automatic visual switching when DJing.

Structure (Denon mode):
  Composition "Will See"
    └── Deck "Will See"
        ├── Layer "Deck 1"  → [Track1_video, Track2_video, ...]
        └── Layer "Deck 2"  → [Track1_video, Track2_video, ...]

Each clip uses transport="Denon" with denonTrackName matching the
ID3 title tag exactly, so Resolume auto-switches visuals when the
DJ loads a new track on a Denon player.

Production workflow:
  1. build_production_show() — creates .avc XML + manifest.json
  2. push_show_to_resolume() — uses REST API to load clips into live Arena
  3. rebuild_show() — re-scans NAS output and rebuilds everything
"""
import json
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from xml.dom import minidom

from .export import LAYER_CONFIG, _LABEL_TO_LAYER

logger = logging.getLogger(__name__)

# Default show name
DEFAULT_SHOW_NAME = "Will See"


def build_production_show(
    tracks: list[dict],
    output_path: Path,
    show_name: str = DEFAULT_SHOW_NAME,
) -> dict:
    """Build the production Resolume .avc composition.

    Each track becomes a clip in a single layer, one per column.
    All clips use Denon transport mode with track title matching.

    The composition file should be placed at the TOP of the vj-content
    folder structure, with clip paths relative to it.

    Args:
        tracks: list of dicts with:
            - title: str (MUST match ID3 title tag exactly)
            - artist: str
            - video_path: str (path to .mov as Resolume will see it)
            - bpm: float (optional)
            - duration: float (optional)
        output_path: Where to save the .avc file
        show_name: Name of the composition (default: "Will See")

    Returns:
        Dict with show metadata including path, track count, manifest path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not tracks:
        raise ValueError("No tracks provided")

    # Validate tracks have required fields
    valid_tracks = []
    for t in tracks:
        title = t.get("title", "").strip()
        video_path = t.get("video_path", t.get("local_vj_path", "")).strip()
        if not title:
            logger.warning(f"Track missing title, skipping: {t}")
            continue
        if not video_path:
            logger.warning(f"Track '{title}' missing video_path, skipping")
            continue
        valid_tracks.append({
            "title": title,
            "artist": t.get("artist", "Unknown"),
            "video_path": video_path,
            "bpm": t.get("bpm", 0.0),
            "duration": t.get("duration", 0.0),
        })

    if not valid_tracks:
        raise ValueError("No valid tracks after filtering (need title + video_path)")

    # Build the .avc XML
    avc_path = _build_avc_xml(valid_tracks, output_path, show_name)

    # Build the manifest (machine-readable track list for rebuilds)
    manifest = _build_manifest(valid_tracks, output_path, show_name)

    result = {
        "show_name": show_name,
        "avc_path": str(avc_path),
        "manifest_path": str(manifest["manifest_path"]),
        "track_count": len(valid_tracks),
        "tracks": [t["title"] for t in valid_tracks],
    }

    logger.info(
        f"Production show '{show_name}': {len(valid_tracks)} tracks -> {avc_path}"
    )
    return result


def add_track_to_show(
    track: dict,
    manifest_path: Path,
    output_path: Optional[Path] = None,
) -> dict:
    """Add a single track to an existing show.

    Reads the manifest, appends the track (if not already present),
    rebuilds the .avc file.

    Args:
        track: Track dict with title, artist, video_path, bpm, duration.
        manifest_path: Path to the existing manifest.json.
        output_path: Path for the .avc file. If None, uses the manifest's path.

    Returns:
        Updated show metadata.
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    tracks = manifest.get("tracks", [])
    show_name = manifest.get("show_name", DEFAULT_SHOW_NAME)

    # Check for duplicate by title
    title = track.get("title", "").strip()
    existing_titles = {t["title"] for t in tracks}
    if title in existing_titles:
        logger.info(f"Track '{title}' already in show, updating")
        tracks = [t for t in tracks if t["title"] != title]

    tracks.append(track)

    # Determine output path
    if output_path is None:
        avc_path_str = manifest.get("avc_path", "")
        if avc_path_str:
            output_path = Path(avc_path_str)
        else:
            output_path = manifest_path.parent / f"{show_name}.avc"

    return build_production_show(tracks, output_path, show_name)


def list_show_tracks(manifest_path: Path) -> list[dict]:
    """List all tracks in a show manifest.

    Args:
        manifest_path: Path to the manifest.json file.

    Returns:
        List of track dicts.
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    return manifest.get("tracks", [])


def rebuild_show_from_output_dir(
    output_base: Path,
    show_path: Path,
    show_name: str = DEFAULT_SHOW_NAME,
) -> dict:
    """Scan an output directory for track_metadata.json files and rebuild.

    Looks for track metadata in each subdirectory and builds the
    production show from all found tracks.

    Args:
        output_base: Directory containing per-track output folders.
        show_path: Where to save the .avc file.
        show_name: Composition name.

    Returns:
        Show metadata dict.
    """
    output_base = Path(output_base)
    tracks = []

    for track_dir in sorted(output_base.iterdir()):
        if not track_dir.is_dir():
            continue

        # Try track_metadata.json first, then metadata.json
        meta_path = track_dir / "track_metadata.json"
        if not meta_path.exists():
            meta_path = track_dir / "metadata.json"
        if not meta_path.exists():
            continue

        try:
            meta = json.loads(meta_path.read_text())
            tracks.append({
                "title": meta.get("title", track_dir.name),
                "artist": meta.get("artist", "Unknown"),
                "video_path": meta.get("local_vj_path", meta.get("video_path", "")),
                "bpm": meta.get("bpm", 0.0),
                "duration": meta.get("duration", 0.0),
            })
            logger.info(f"  Found: {meta.get('title', track_dir.name)}")
        except Exception as e:
            logger.warning(f"  Skipped {track_dir.name}: {e}")

    if not tracks:
        raise ValueError(f"No tracks found in {output_base}")

    logger.info(f"Rebuilding show from {len(tracks)} tracks")
    return build_production_show(tracks, show_path, show_name)


def auto_rebuild_show(
    nas_manager,
    show_name: str = "Will See",
) -> Path:
    """Scan NAS Songs folder, rebuild .avc with all found tracks, push to NAS.

    Called automatically after each track generation. Discovers all track
    folders on NAS that have a metadata.json, builds the .avc composition
    with every track, and pushes the updated .avc back to NAS.

    Args:
        nas_manager: NASManager instance for NAS communication.
        show_name: Name of the composition (default: "Will See").

    Returns:
        Path to the local .avc file that was built and pushed.
    """
    import tempfile

    # Discover all tracks on NAS
    track_titles = nas_manager.list_tracks()
    if not track_titles:
        raise ValueError("No tracks found on NAS to build show from")

    tracks = []
    for title in track_titles:
        # Check that the track has a video file
        if not nas_manager.track_has_video(title):
            logger.debug(f"  Skipping '{title}': no video file")
            continue

        # Pull metadata if available
        meta = nas_manager.pull_metadata(title)

        tracks.append({
            "title": title,
            "artist": meta.get("artist", "Unknown"),
            "video_path": nas_manager.get_track_video_path(title),
            "bpm": meta.get("bpm", 0.0),
            "duration": meta.get("duration", 0.0),
        })

    if not tracks:
        raise ValueError("No tracks with video files found on NAS")

    logger.info(f"Auto-rebuild: found {len(tracks)} tracks with videos")

    # Build .avc in a temp directory, then push to NAS
    tmpdir = tempfile.mkdtemp(prefix="rsv_show_")
    avc_path = Path(tmpdir) / f"{show_name}.avc"

    result = build_production_show(tracks, avc_path, show_name)
    avc_path = Path(result["avc_path"])

    # Push the .avc to NAS
    nas_manager.push_show(avc_path, show_name)

    logger.info(
        f"Auto-rebuild complete: '{show_name}' with {len(tracks)} tracks "
        f"pushed to NAS"
    )
    return avc_path


def push_show_to_resolume(
    manifest_path: Path,
    host: str = "127.0.0.1",
    port: int = 8080,
    layer: int = 1,
) -> dict:
    """Push a show manifest to a running Resolume instance via REST API.

    Loads each track's video into Resolume, sets Denon transport mode,
    and configures clip targets for auto-matching.

    Args:
        manifest_path: Path to the show manifest.json.
        host: Resolume Arena host.
        port: Resolume Arena REST API port.
        layer: Which layer to load clips into (1-indexed).

    Returns:
        Dict with results.
    """
    from .api import ResolumeAPI

    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    tracks = manifest.get("tracks", [])

    if not tracks:
        raise ValueError("No tracks in manifest")

    with ResolumeAPI(host=host, port=port) as api:
        if not api.is_connected():
            raise ConnectionError(
                f"Cannot connect to Resolume at {host}:{port}. "
                "Is Arena running with the webserver enabled?"
            )

        loaded = api.build_denon_show(tracks, layer=layer)

    return {
        "show_name": manifest.get("show_name", DEFAULT_SHOW_NAME),
        "loaded": loaded,
        "total": len(tracks),
        "host": host,
        "port": port,
        "layer": layer,
    }


# ------------------------------------------------------------------
# Private: .avc XML builder
# ------------------------------------------------------------------

def _build_avc_xml(
    tracks: list[dict],
    output_path: Path,
    show_name: str,
) -> Path:
    """Generate the Resolume Arena .avc composition XML.

    NOTE: The .avc format is undocumented and internal to Resolume.
    This generates a best-effort XML that Resolume 7+ can open.
    The structure is based on reverse-engineering real .avc files
    and the Resolume REST API data model.

    For production use, prefer push_show_to_resolume() which uses
    the official REST API to load clips into a running instance,
    then save from within Resolume for a guaranteed-valid .avc.

    The XML structure follows the pattern from real .avc files:
    - Root: <Composition>
    - Contains: versionInfo, CompositionInfo, Params, VideoTrack,
      AudioTrack, Layer(s), Column(s), Deck(s), TempoController
    - Clips are embedded within Layers, one per column position
    """
    import uuid

    def _uid():
        return str(int(time.time() * 1000) + hash(uuid.uuid4().hex[:8]) % 100000)

    comp = ET.Element("Composition")
    comp.set("name", show_name)
    comp.set("uniqueId", _uid())
    comp.set("numDecks", "1")
    comp.set("currentDeckIndex", "0")
    comp.set("numLayers", "1")
    comp.set("numColumns", str(len(tracks)))
    comp.set("compositionIsRelative", "0")

    # Version info
    ver = ET.SubElement(comp, "versionInfo")
    ver.set("name", "Resolume Arena")
    ver.set("majorVersion", "7")
    ver.set("minorVersion", "0")
    ver.set("microVersion", "0")
    ver.set("revision", "0")

    # CompositionInfo
    comp_info = ET.SubElement(comp, "CompositionInfo")
    comp_info.set("name", show_name)
    comp_info.set("description", f"Auto-generated Denon show: {len(tracks)} tracks")
    comp_info.set("width", "1920")
    comp_info.set("height", "1080")
    deck_info = ET.SubElement(comp_info, "DeckInfo")
    deck_info.set("name", show_name)
    deck_info.set("id", _uid())
    deck_info.set("closed", "0")

    # Composition Params
    params = ET.SubElement(comp, "Params")
    params.set("name", "Params")
    _add_param(params, "Name", show_name)
    _add_param(params, "Description", f"Denon show: {len(tracks)} tracks")

    # AudioTrack (composition level)
    audio = ET.SubElement(comp, "AudioTrack")
    audio.set("name", "AudioTrack")
    ET.SubElement(audio, "AudioEffectChain").set("name", "AudioEffectChain")

    # VideoTrack (composition level)
    video = ET.SubElement(comp, "VideoTrack")
    video.set("name", "VideoTrack")
    vparams = ET.SubElement(video, "Params")
    vparams.set("name", "Params")
    _add_param_range(vparams, "Width", "1920", storage="3")
    _add_param_range(vparams, "Height", "1080", storage="3")
    _add_param_range(vparams, "FrameRate", "30")

    # Single Layer for all clips
    layer = ET.SubElement(comp, "Layer")
    layer.set("uniqueId", _uid())
    layer.set("layerIndex", "0")

    layer_params = ET.SubElement(layer, "Params")
    layer_params.set("name", "Params")
    _add_param(layer_params, "Name", "Denon Visuals")

    # Layer AudioTrack
    layer_audio = ET.SubElement(layer, "AudioTrack")
    layer_audio.set("name", "AudioTrack")
    ET.SubElement(layer_audio, "AudioEffectChain").set("name", "AudioEffectChain")

    # Layer VideoTrack
    layer_video = ET.SubElement(layer, "VideoTrack")
    layer_video.set("name", "VideoTrack")
    lv_params = ET.SubElement(layer_video, "Params")
    lv_params.set("name", "Params")
    _add_param_range(lv_params, "Width", "1920", storage="3")
    _add_param_range(lv_params, "Height", "1080", storage="3")

    # Clips within the layer -- one per track
    for col_idx, track in enumerate(tracks):
        clip = ET.SubElement(layer, "Clip")
        clip.set("uniqueId", _uid())
        clip.set("clipIndex", str(col_idx))

        clip_params = ET.SubElement(clip, "Params")
        clip_params.set("name", "Params")
        _add_param(clip_params, "Name", track["title"])

        # Primary source: the video file
        source = ET.SubElement(clip, "PrimarySource")
        source.set("name", "PrimarySource")
        video_source = ET.SubElement(source, "VideoSource")
        video_source.set("type", "file")
        video_source.set("couldContainVideo", "1")
        video_source.set("couldContainAudio", "0")
        file_ref = ET.SubElement(video_source, "VideoFormatReaderSource")
        file_ref.set("fileName", track["video_path"])

        # Clip VideoTrack
        clip_video = ET.SubElement(clip, "VideoTrack")
        clip_video.set("name", "VideoTrack")
        cv_params = ET.SubElement(clip_video, "Params")
        cv_params.set("name", "Params")
        _add_param_range(cv_params, "Width", "1920", storage="3")
        _add_param_range(cv_params, "Height", "1080", storage="3")

        # Transport: Denon mode
        # In the .avc XML, transport type is stored as a ParamChoice
        # The denonTrackName should match the ID3 title
        transport = ET.SubElement(clip, "Transport")
        transport.set("name", "Transport")
        _add_param_choice(
            transport, "Transport Type", "Denon", "Denon"
        )
        _add_param(transport, "DenonTrackName", track["title"])

        # Duration source
        duration = ET.SubElement(clip, "DurationSource")
        duration.set("name", "DurationSource")
        if track.get("duration", 0) > 0:
            dur_ms = int(track["duration"] * 1000)
            ET.SubElement(duration, "PhaseSourceTransportTimeline").set(
                "defaultMillisecondsDuration", str(dur_ms)
            )

    # Columns
    for col_idx, track in enumerate(tracks):
        col = ET.SubElement(comp, "Column")
        col.set("uniqueId", _uid())
        col.set("columnIndex", str(col_idx))
        col_params = ET.SubElement(col, "Params")
        col_params.set("name", "Params")
        _add_param(col_params, "Name", track["title"])

    # TempoController
    tempo = ET.SubElement(comp, "TempoController")
    tempo.set("name", "TempoController")

    # Deck
    deck = ET.SubElement(comp, "Deck")
    deck.set("name", "Deck")
    deck.set("uniqueId", _uid())
    deck.set("closed", "0")
    deck.set("numLayers", "1")
    deck.set("numColumns", str(len(tracks)))
    deck.set("deckIndex", "0")
    deck_params = ET.SubElement(deck, "Params")
    deck_params.set("name", "Params")
    _add_param(deck_params, "Name", show_name)

    for col_idx, track in enumerate(tracks):
        col_attr = ET.SubElement(deck, "ColumnAttributes")
        col_attr.set("index", str(col_idx))
        col_attr.set("name", track["title"])
        col_attr.set("color", "0")

    # Write XML
    xml_str = _prettify_xml(comp)
    output_path.write_text(xml_str, encoding="utf-8")

    logger.info(f"AVC written: {output_path} ({len(tracks)} clips)")
    return output_path


def _build_manifest(
    tracks: list[dict],
    avc_path: Path,
    show_name: str,
) -> dict:
    """Build and save a JSON manifest alongside the .avc file."""
    manifest_path = avc_path.parent / f"{show_name}.manifest.json"

    manifest = {
        "show_name": show_name,
        "avc_path": str(avc_path),
        "track_count": len(tracks),
        "tracks": tracks,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    logger.info(f"Manifest written: {manifest_path}")
    return manifest


def _add_param(parent: ET.Element, name: str, value: str):
    """Add a simple <Param> element."""
    p = ET.SubElement(parent, "Param")
    p.set("name", name)
    p.set("default", "")
    p.set("value", value)


def _add_param_range(
    parent: ET.Element,
    name: str,
    value: str,
    default: Optional[str] = None,
    storage: Optional[str] = None,
):
    """Add a <ParamRange> element."""
    p = ET.SubElement(parent, "ParamRange")
    if storage:
        p.set("storage", storage)
    p.set("name", name)
    p.set("default", default or value)
    p.set("value", value)


def _add_param_choice(
    parent: ET.Element,
    name: str,
    value: str,
    default: str,
):
    """Add a <ParamChoice> element."""
    p = ET.SubElement(parent, "ParamChoice")
    p.set("name", name)
    p.set("default", default)
    p.set("value", value)
    p.set("storeChoices", "0")


# ------------------------------------------------------------------
# Legacy functions (preserved for backward compatibility)
# ------------------------------------------------------------------


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
    logger.info(f"Show composition '{show_name}': {n_tracks} tracks, {total_clips} clips -> {output_path}")
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


def create_denon_show_composition(
    tracks: list[dict],
    output_path: str | Path,
    show_name: str = "Will See",
    n_decks: int = 2,
) -> Path:
    """
    Create a Resolume .avc composition using Denon transport mode.

    Each track becomes a clip in each layer (one layer per Denon deck).
    Resolume auto-triggers the matching clip when a track is loaded
    on a Denon player, based on the denonTrackName matching the ID3 title.

    Args:
        tracks: List of track dicts. Each should have:
            - title: str (must EXACTLY match ID3 title tag)
            - local_vj_path: str (path to .mov as seen by Resolume's Mac)
            - bpm: float (optional, for reference)
            - artist: str (optional, for reference)
        output_path: Where to save the .avc file
        show_name: Name of the composition (default: "Will See")
        n_decks: Number of Denon decks / layers (default: 2)

    Returns:
        Path to the .avc file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not tracks:
        raise ValueError("No tracks provided")

    arena = ET.Element("Arena")
    composition = ET.SubElement(arena, "Composition", name=show_name)

    # Single deck for the whole show
    deck = ET.SubElement(composition, "Deck", name=show_name)

    # One layer per Denon deck -- each layer gets ALL clips
    total_clips = 0
    for deck_num in range(1, n_decks + 1):
        layer_elem = ET.SubElement(
            deck, "Layer",
            name=f"Deck {deck_num}",
        )

        for track_data in tracks:
            title = track_data.get("title", "Unknown")
            vj_path = track_data.get("local_vj_path", "")

            clip_elem = ET.SubElement(
                layer_elem, "Clip",
                name=title,
                transport="Denon",
                denonTrackName=title,
            )
            ET.SubElement(clip_elem, "Source", path=vj_path)
            ET.SubElement(clip_elem, "Video", width="1920", height="1080")
            total_clips += 1

    # Write XML
    xml_str = _prettify_xml(arena)
    output_path.write_text(xml_str, encoding="utf-8")

    n_tracks = len(tracks)
    logger.info(
        f"Denon show composition '{show_name}': "
        f"{n_tracks} tracks, {n_decks} decks, {total_clips} clips -> {output_path}"
    )
    return output_path


def build_denon_show_from_output_dir(
    output_base: str | Path,
    show_path: str | Path,
    show_name: str = "Will See",
) -> Path:
    """
    Scan an output directory for generated track metadata and build
    a Denon transport mode .avc composition.

    Looks for track_metadata.json files in each subdirectory.

    Args:
        output_base: Directory containing per-track output folders
        show_path: Where to save the .avc file
        show_name: Composition name

    Returns:
        Path to the .avc file
    """
    output_base = Path(output_base)
    tracks = []

    for track_dir in sorted(output_base.iterdir()):
        meta_path = track_dir / "track_metadata.json"
        if not meta_path.exists():
            continue

        try:
            meta = json.loads(meta_path.read_text())
            tracks.append(meta)
            logger.info(f"  Found: {meta.get('title', track_dir.name)}")
        except Exception as e:
            logger.warning(f"  Skipped {track_dir.name}: {e}")

    if not tracks:
        raise ValueError(f"No tracks found in {output_base}")

    logger.info(f"Building Denon show from {len(tracks)} tracks")
    return create_denon_show_composition(tracks, show_path, show_name)


def _prettify_xml(element: ET.Element) -> str:
    """Pretty-print XML with indentation."""
    rough = ET.tostring(element, encoding="unicode", xml_declaration=True)
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding=None)
