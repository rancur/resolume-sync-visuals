"""
Resolume Arena export module.
Organizes generated clips into Resolume's deck/layer/column structure
and generates OSC control scripts for live triggering.

Resolume Arena Concepts:
- Composition: The top-level project (one per set/show)
- Layers: Stacked vertically, blended together (like Photoshop layers)
- Columns: Horizontal slots — triggering a column fires one clip per layer
- Deck: A bank of layers+columns that can be swapped
- Transport: BPM Sync makes clips loop in time with the master clock
"""
import json
import logging
import shutil
import textwrap
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolume layer assignments by phrase type.
# Layer 1 is the bottom (background), higher layers overlay.
LAYER_CONFIG = {
    1: {
        "name": "Drops",
        "labels": ["drop"],
        "description": "High-energy drop visuals — maximum intensity",
        "blend_mode": "Add",
        "opacity": 1.0,
    },
    2: {
        "name": "Buildups",
        "labels": ["buildup"],
        "description": "Rising energy clips for tension and anticipation",
        "blend_mode": "Screen",
        "opacity": 0.9,
    },
    3: {
        "name": "Breakdowns",
        "labels": ["breakdown"],
        "description": "Low-energy atmospheric clips for contrast",
        "blend_mode": "Screen",
        "opacity": 0.85,
    },
    4: {
        "name": "Ambient",
        "labels": ["intro", "outro"],
        "description": "Intro/outro ambient textures and transitions",
        "blend_mode": "Multiply",
        "opacity": 0.7,
    },
}

# Invert for fast lookup: label -> layer number
_LABEL_TO_LAYER = {}
for layer_num, cfg in LAYER_CONFIG.items():
    for label in cfg["labels"]:
        _LABEL_TO_LAYER[label] = layer_num

# Default Resolume OSC port
RESOLUME_OSC_PORT = 7000


def create_resolume_deck(composition: dict, output_dir: str | Path) -> Path:
    """
    Organize composition output into Resolume-friendly folder structure.

    Creates:
        output_dir/resolume/
            Layer1_Drops/
                001_drop.mp4
                002_drop.mp4
            Layer2_Buildups/
                001_buildup.mp4
            Layer3_Breakdowns/
                001_breakdown.mp4
            Layer4_Ambient/
                001_intro.mp4
                002_outro.mp4
            deck_info.json

    Args:
        composition: Composition metadata dict from compose_timeline()
        output_dir: Base output directory for this track

    Returns:
        Path to the resolume/ directory
    """
    output_dir = Path(output_dir)
    resolume_dir = output_dir / "resolume"
    resolume_dir.mkdir(parents=True, exist_ok=True)

    # Create layer directories
    layer_dirs = {}
    for layer_num, cfg in LAYER_CONFIG.items():
        dir_name = f"Layer{layer_num}_{cfg['name']}"
        layer_dir = resolume_dir / dir_name
        layer_dir.mkdir(parents=True, exist_ok=True)
        layer_dirs[layer_num] = layer_dir

    # Sort loops into layers, maintaining order
    layer_clips = {n: [] for n in LAYER_CONFIG}
    loops = composition.get("loops", [])
    clips_fallback = composition.get("clips", [])

    # Prefer loops (seamless); fall back to raw clips if no loops
    source_clips = loops if loops else clips_fallback

    for clip in source_clips:
        label = clip.get("label", "intro")
        layer_num = _LABEL_TO_LAYER.get(label, 4)
        layer_clips[layer_num].append(clip)

    # Copy clips into layer directories with sequential naming
    deck_layers = {}
    total_copied = 0

    for layer_num, clips in layer_clips.items():
        layer_dir = layer_dirs[layer_num]
        layer_cfg = LAYER_CONFIG[layer_num]
        layer_entries = []

        for idx, clip in enumerate(clips):
            src = Path(clip["file"])
            if not src.exists():
                logger.warning(f"Source clip not found, skipping: {src}")
                continue

            # Sequential name: 001_drop.mp4
            label = clip.get("label", "clip")
            dst_name = f"{idx + 1:03d}_{label}{src.suffix}"
            dst = layer_dir / dst_name
            shutil.copy2(src, dst)
            total_copied += 1

            layer_entries.append({
                "file": dst_name,
                "column": idx,
                "label": label,
                "beats": clip.get("beats", 0),
                "bars": clip.get("bars", 0),
                "duration": clip.get("duration", 0),
                "bpm": clip.get("bpm", composition.get("bpm", 0)),
                "transport": "BPM Sync",
                "trigger_mode": "Column",
            })

        deck_layers[layer_num] = {
            "name": layer_cfg["name"],
            "directory": f"Layer{layer_num}_{layer_cfg['name']}",
            "description": layer_cfg["description"],
            "blend_mode": layer_cfg["blend_mode"],
            "opacity": layer_cfg["opacity"],
            "clips": layer_entries,
        }

    # Build deck_info.json
    bpm = composition.get("bpm", 120)
    deck_info = {
        "track": composition.get("track", "Unknown"),
        "bpm": bpm,
        "time_signature": f"{composition.get('time_signature', 4)}/4",
        "duration": composition.get("duration", 0),
        "recommended_transport": "BPM Sync",
        "master_bpm_note": (
            f"Set Resolume's master BPM to {bpm:.1f} for perfect sync. "
            "Enable BPM Sync on all clips via Clip > Transport > BPM Sync."
        ),
        "layers": deck_layers,
        "total_clips": total_copied,
        "clip_order_note": (
            "Clips are numbered sequentially within each layer. "
            "Column numbers correspond to phrase order in the original track."
        ),
        "import_instructions": [
            f"1. Set Resolume master BPM to {bpm:.1f}",
            "2. Drag each Layer folder onto its corresponding Resolume layer",
            "3. Set all clip transport modes to 'BPM Sync'",
            "4. Set trigger mode to 'Column' for synchronized playback",
            "5. Trigger columns left-to-right to follow the song structure",
        ],
    }

    info_path = resolume_dir / "deck_info.json"
    info_path.write_text(json.dumps(deck_info, indent=2))

    logger.info(
        f"Resolume deck created: {total_copied} clips across "
        f"{sum(1 for l in deck_layers.values() if l['clips'])} layers → {resolume_dir}"
    )

    return resolume_dir


def generate_resolume_osc_script(composition: dict, output_path: str | Path = None) -> str:
    """
    Generate a standalone Python script that sends OSC messages to Resolume
    to trigger clips in sync with the track structure.

    The generated script uses python-osc and can be run independently.
    Resolume listens for OSC on port 7000 by default.

    Args:
        composition: Composition metadata dict from compose_timeline()
        output_path: Where to write the script. If None, returns the script text.

    Returns:
        The generated Python script as a string
    """
    bpm = composition.get("bpm", 120)
    track_name = composition.get("track", "Unknown")
    time_sig = composition.get("time_signature", 4)
    beat_duration = 60.0 / bpm

    # Build the clip trigger sequence from resolume_mapping or loops
    mapping = composition.get("resolume_mapping", [])
    if not mapping:
        # Fall back to building from loops
        mapping = _build_mapping_from_loops(composition)

    # Build trigger events: list of (time_offset, layer, column, label)
    trigger_events = []
    time_cursor = 0.0

    for entry in mapping:
        layer = entry.get("layer", 1)
        column = entry.get("column", 0)
        label = entry.get("label", "clip")
        beats = entry.get("beats", 16)
        duration = beats * beat_duration

        trigger_events.append({
            "time": round(time_cursor, 3),
            "layer": layer,
            "column": column + 1,  # Resolume uses 1-based columns
            "label": label,
            "beats": beats,
        })
        time_cursor += duration

    # Generate the script
    events_json = json.dumps(trigger_events, indent=4)

    # Indent the events JSON for embedding
    events_indented = events_json.replace("\n", "\n")

    script = (
        f'#!/usr/bin/env python3\n'
        f'"""\n'
        f'Resolume Arena OSC Trigger Script\n'
        f'Generated for: {track_name}\n'
        f'BPM: {bpm:.1f} | Time Signature: {time_sig}/4\n'
        f'\n'
        f'Requirements:\n'
        f'    pip install python-osc\n'
        f'\n'
        f'Usage:\n'
        f'    python osc_trigger.py                     # Default: localhost:7000\n'
        f'    python osc_trigger.py --host 10.0.0.5     # Remote Resolume instance\n'
        f'    python osc_trigger.py --dry-run            # Preview without sending\n'
        f'"""\n'
        f'import argparse\n'
        f'import time\n'
        f'import sys\n'
        f'\n'
        f'try:\n'
        f'    from pythonosc import udp_client\n'
        f'except ImportError:\n'
        f'    print("ERROR: python-osc is required. Install with: pip install python-osc")\n'
        f'    sys.exit(1)\n'
        f'\n'
        f'\n'
        f'TRACK = "{track_name}"\n'
        f'BPM = {bpm:.1f}\n'
        f'TIME_SIGNATURE = {time_sig}\n'
        f'BEAT_DURATION = {beat_duration:.6f}\n'
        f'\n'
        f'TRIGGER_EVENTS = {events_indented}\n'
        f'\n'
        f'\n'
        f'def trigger_clip(client, layer: int, column: int):\n'
        f'    address = f"/composition/layers/{{layer}}/clips/{{column}}/connect"\n'
        f'    client.send_message(address, 1)\n'
        f'\n'
        f'\n'
        f'def set_master_bpm(client, bpm: float):\n'
        f'    client.send_message("/composition/tempocontroller/tempo", bpm)\n'
        f'\n'
        f'\n'
        f'def clear_layer(client, layer: int):\n'
        f'    client.send_message(f"/composition/layers/{{layer}}/clear", 1)\n'
        f'\n'
        f'\n'
        f'def main():\n'
        f'    parser = argparse.ArgumentParser(\n'
        f'        description=f"OSC trigger script for {{TRACK}} ({{BPM}} BPM)"\n'
        f'    )\n'
        f'    parser.add_argument("--host", default="127.0.0.1", help="Resolume host IP")\n'
        f'    parser.add_argument("--port", type=int, default={RESOLUME_OSC_PORT}, help="Resolume OSC port")\n'
        f'    parser.add_argument("--dry-run", action="store_true", help="Preview triggers")\n'
        f'    parser.add_argument("--offset", type=float, default=0.0, help="Start time offset")\n'
        f'    parser.add_argument("--skip-bpm", action="store_true", help="Skip setting master BPM")\n'
        f'    args = parser.parse_args()\n'
        f'\n'
        f'    if not args.dry_run:\n'
        f'        client = udp_client.SimpleUDPClient(args.host, args.port)\n'
        f'        print(f"Connected to Resolume at {{args.host}}:{{args.port}}")\n'
        f'        if not args.skip_bpm:\n'
        f'            set_master_bpm(client, BPM)\n'
        f'            print(f"Set master BPM to {{BPM}}")\n'
        f'    else:\n'
        f'        client = None\n'
        f'        print("[DRY RUN] No OSC messages will be sent")\n'
        f'\n'
        f'    print(f"\\nTrack: {{TRACK}}")\n'
        f'    print(f"BPM: {{BPM}} | Beat: {{BEAT_DURATION:.3f}}s")\n'
        f'    print(f"Events: {{len(TRIGGER_EVENTS)}}")\n'
        f'    print("\\nStarting in 3 seconds... (press Ctrl+C to abort)")\n'
        f'    time.sleep(3)\n'
        f'\n'
        f'    print("\\n--- PLAYBACK START ---\\n")\n'
        f'    start_time = time.time() - args.offset\n'
        f'\n'
        f'    for i, event in enumerate(TRIGGER_EVENTS):\n'
        f'        target_time = start_time + event["time"]\n'
        f'        now = time.time()\n'
        f'        wait = target_time - now\n'
        f'        if wait > 0:\n'
        f'            time.sleep(wait)\n'
        f'\n'
        f'        layer = event["layer"]\n'
        f'        column = event["column"]\n'
        f'        label = event["label"]\n'
        f'        beats = event["beats"]\n'
        f'        elapsed = time.time() - start_time\n'
        f'\n'
        f'        status = f"[{{elapsed:7.2f}}s] Layer {{layer}} / Col {{column:2d}} | {{label:<12s}} ({{beats}} beats)"\n'
        f'        if client:\n'
        f'            trigger_clip(client, layer, column)\n'
        f'            print(f"  TRIGGER  {{status}}")\n'
        f'        else:\n'
        f'            print(f"  (dry)    {{status}}")\n'
        f'\n'
        f'    print("\\n--- PLAYBACK COMPLETE ---")\n'
        f'\n'
        f'\n'
        f'if __name__ == "__main__":\n'
        f'    main()\n'
    )

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(script)
        # Make executable
        output_path.chmod(0o755)
        logger.info(f"OSC trigger script written to {output_path}")

    return script


def _build_mapping_from_loops(composition: dict) -> list[dict]:
    """Build a resolume_mapping list from loops if not already present."""
    loops = composition.get("loops", [])
    bpm = composition.get("bpm", 120)
    time_sig = composition.get("time_signature", 4)

    column_counters = {}
    mapping = []

    for loop in loops:
        label = loop.get("label", "intro")
        layer = _LABEL_TO_LAYER.get(label, 4)

        if layer not in column_counters:
            column_counters[layer] = 0

        col = column_counters[layer]
        column_counters[layer] = col + 1

        mapping.append({
            "file": loop.get("file", ""),
            "layer": layer,
            "column": col,
            "label": label,
            "bpm": bpm,
            "beats": loop.get("beats", 16),
            "transport": "BPM Sync",
            "trigger": "Column",
        })

    return mapping
