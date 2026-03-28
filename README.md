# Resolume Sync Visuals

AI-powered beat-synced visual loop generator for **Resolume Arena**. Analyze any music track, generate perfectly-timed visual loops using AI image models, and export organized clip packs ready for live VJ performance.

Built for VJs, visual artists, and electronic music performers who need custom visuals that lock to the beat without manual keyframing.

## Features

- **Automatic beat/phrase detection** -- librosa-powered BPM, beat, and phrase analysis with EDM structure labeling (intro, buildup, drop, breakdown, outro)
- **AI image generation** -- DALL-E 3 (OpenAI) or Flux Schnell (Replicate) keyframe generation with style-aware prompts
- **Beat-synced animation** -- Cross-dissolve, zoom pulse, brightness flash, and motion blur effects locked to BPM
- **Seamless loops** -- Every clip loops perfectly at beat-quantized boundaries
- **8 style presets** -- Abstract, Cyberpunk, Laser, Liquid, Nature, Fractal, Glitch, Cosmic (or bring your own YAML)
- **Resolume deck export** -- Organized Layer/Column folder structure with deck_info.json
- **OSC trigger scripts** -- Auto-generated Python scripts to control Resolume via OSC in sync with your track
- **Bulk processing** -- Process an entire set folder in one command
- **Caching** -- Generated keyframes are cached by prompt hash to avoid redundant API calls

## Architecture

```
                    Audio File (.flac / .mp3 / .wav)
                                 |
                    +------------v------------+
                    |   Analyzer (librosa)    |
                    |  BPM, beats, phrases,   |
                    |  energy, structure       |
                    +------------+------------+
                                 |
                         TrackAnalysis
                                 |
          +----------------------+----------------------+
          |                                             |
+---------v----------+                     +------------v-----------+
| Feature Extractor  |                     |   Style Config (YAML)  |
| beat intensity,    |                     |   prompts, colors,     |
| brightness, warmth |                     |   effects per phrase   |
+--------+-----------+                     +------------+-----------+
          |                                             |
          +---------------------+-----------------------+
                                |
                   +------------v------------+
                   |  Generation Engine      |
                   |  DALL-E 3 / Replicate   |
                   |  keyframes -> animation |
                   |  beat-sync effects      |
                   |  ffmpeg encoding        |
                   +------------+------------+
                                |
                         Clip per phrase
                                |
                   +------------v------------+
                   |  Timeline Composer      |
                   |  loop extension,        |
                   |  clip organization,     |
                   |  metadata generation    |
                   +------------+------------+
                                |
          +---------------------+---------------------+
          |                                           |
+---------v----------+                   +------------v-----------+
|  Resolume Export   |                   |   OSC Trigger Script   |
|  Layer folders,    |                   |   python-osc commands  |
|  deck_info.json    |                   |   per-clip timing      |
+--------------------+                   +------------------------+
```

## Installation

### Prerequisites

- **Python 3.9+**
- **ffmpeg** (must be on PATH)
- An API key for **OpenAI** (DALL-E 3) or **Replicate** (Flux Schnell)

### Setup

```bash
# Clone the repo
git clone https://github.com/willcurran/resolume-sync-visuals.git
cd resolume-sync-visuals

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e ".[dev]"

# Verify ffmpeg is available
ffmpeg -version
```

### API Keys

Set your image generation API key as an environment variable. Never commit keys to the repo.

```bash
# OpenAI (DALL-E 3)
export OPENAI_API_KEY="sk-..."

# Replicate (Flux Schnell) -- optional alternative
export REPLICATE_API_TOKEN="r8_..."
```

If you use 1Password, inject at runtime:

```bash
op run --env-file=.env -- rsv generate track.flac
```

## Quick Start

### 1. Analyze a track

```bash
rsv analyze my_track.flac
```

This prints BPM, time signature, phrase count, and a labeled structure breakdown (intro, buildup, drop, breakdown, outro) without generating any visuals.

Save the analysis to JSON:

```bash
rsv analyze my_track.flac --output analysis.json
```

### 2. Generate visuals

```bash
rsv generate my_track.flac --style cyberpunk --backend openai
```

This will:
1. Analyze the track (BPM, beats, phrases)
2. Generate AI keyframe images for each phrase
3. Animate keyframes with beat-synced effects
4. Encode seamless looping MP4 clips via ffmpeg
5. Organize output into `output/<track_name>/`

### 3. Export for Resolume

The generator automatically creates a `metadata.json` with Resolume mapping. To create the full Resolume deck folder structure with an OSC trigger script, use the export module in your own script or integrate it into the pipeline:

```python
from src.resolume.export import create_resolume_deck, generate_resolume_osc_script
import json

# Load the composition metadata from a previous run
with open("output/My_Track/metadata.json") as f:
    composition = json.load(f)

# Create organized Resolume folder structure
create_resolume_deck(composition, "output/My_Track")

# Generate OSC trigger script
generate_resolume_osc_script(composition, "output/My_Track/resolume/osc_trigger.py")
```

### 4. Import into Resolume Arena

1. Open Resolume Arena
2. Set the master BPM to match your track (shown in `deck_info.json`)
3. Drag each `LayerN_*` folder onto the corresponding Resolume layer
4. Set all clip transport modes to **BPM Sync**
5. Trigger columns left-to-right to follow the song structure

Or use the generated OSC script for automated triggering:

```bash
pip install python-osc
python output/My_Track/resolume/osc_trigger.py
```

## CLI Reference

### `rsv analyze <file>`

Analyze a music track and display BPM, beat structure, and phrase labels.

| Flag | Default | Description |
|------|---------|-------------|
| `--phrase-beats, -p` | auto | Override phrase length in beats (8, 16, 32) |
| `--output, -o` | none | Save analysis to JSON file |

### `rsv generate <file>`

Generate beat-synced visuals for a single track.

| Flag | Default | Description |
|------|---------|-------------|
| `--style, -s` | `abstract` | Visual style preset name |
| `--backend, -b` | `openai` | Image generation backend (`openai` or `replicate`) |
| `--quality, -q` | `high` | Output quality (`draft`, `standard`, `high`) |
| `--output-dir, -o` | `output` | Base output directory |
| `--loop-beats, -l` | `4` | Loop duration in beats |
| `--phrase-beats, -p` | auto | Override phrase length in beats |
| `--width` | `1920` | Video width in pixels |
| `--height` | `1080` | Video height in pixels |
| `--fps` | `30` | Video frames per second |

### `rsv bulk <directory>`

Process all music files in a directory.

| Flag | Default | Description |
|------|---------|-------------|
| `--style, -s` | `abstract` | Visual style preset |
| `--backend, -b` | `openai` | Image generation backend |
| `--quality, -q` | `high` | Output quality |
| `--output-dir, -o` | `output` | Base output directory |
| `--loop-beats, -l` | `4` | Loop duration in beats |
| `--max-concurrent` | `2` | Max tracks processing at once |
| `--skip-existing` | `true` | Skip already-processed tracks |

Supported file extensions: `.flac`, `.mp3`, `.wav`, `.aif`, `.aiff`, `.ogg`

### `rsv styles`

List all available visual style presets with descriptions and color palettes.

### Global Flags

| Flag | Description |
|------|-------------|
| `--verbose, -v` | Enable debug logging |
| `--config, -c` | Path to custom YAML config file |

## Style Presets

Each style is a YAML file in `config/styles/` that defines prompts, colors, and effect parameters per phrase type.

| Style | Description | Primary Color |
|-------|-------------|---------------|
| **abstract** | Flowing geometric shapes, particle systems, fluid dynamics | Purple / Electric Blue |
| **cyberpunk** | Neon cityscapes, holographic displays, glitch effects | Magenta / Cyan |
| **laser** | Festival laser shows, stage lighting, beam effects | Green / Red |
| **liquid** | Fluid simulations, ink drops, oil-on-water patterns | Magenta / Teal |
| **nature** | Ethereal landscapes, aurora borealis, bioluminescence | Bioluminescent Green / Purple |

### Custom Styles

Create a YAML file following this structure:

```yaml
name: my_style
description: Short description of the visual aesthetic

prompts:
  base: "default prompt for all phrase types, 8k quality"
  drop: "high energy prompt for drops"
  buildup: "rising energy prompt"
  breakdown: "calm atmospheric prompt"
  intro: "opening mood prompt"
  outro: "closing mood prompt"

colors:
  primary: "#FF00FF"
  secondary: "#00FFFF"
  accent: "#FF6B35"
  dark: "#0D0221"

effects:
  beat_flash_intensity: 0.7   # 0-1, brightness flash on beats
  color_shift_speed: 0.8      # 0-1, color cycling rate
  glitch_probability: 0.1     # 0-1, chance of glitch effect per frame
  motion_blur: 0.6            # 0-1, inter-frame blur amount
```

Use a custom style by name or path:

```bash
rsv generate track.flac --style my_style
rsv generate track.flac --style /path/to/custom_style.yaml
```

## Configuration

The default config lives at `config/default.yaml`. Override any value with `--config`:

```bash
rsv generate track.flac --config my_config.yaml
```

### Configuration Reference

```yaml
# Video output
video:
  width: 1920           # Output resolution width
  height: 1080          # Output resolution height
  fps: 30               # Frames per second
  codec: libx264        # ffmpeg video codec
  crf: 18               # Quality (lower = better, 18 = visually lossless)
  preset: slow           # Encoding speed/compression tradeoff

# AI generation
generation:
  backend: openai        # openai or replicate
  style: abstract        # Default style preset
  loop_duration_beats: 4 # Beats per generated loop
  quality: high          # draft (2 keyframes), standard (3), high (up to 4)
  cache_frames: true     # Cache keyframes to avoid re-generating

# Music analysis
analysis:
  sample_rate: 22050     # Audio sample rate for analysis
  phrase_beats: null     # null = auto-detect (8, 16, or 32)
  time_signature: 4      # Beats per bar

# Bulk processing
bulk:
  max_concurrent: 2
  file_extensions: [.flac, .mp3, .wav, .aif, .aiff, .ogg]
  skip_existing: true

# Output
output:
  base_dir: output
  per_track_dirs: true
  include_analysis: true
  include_metadata: true
```

## Resolume Arena Integration

### Output Structure

After generating visuals, each track gets this output:

```
output/<track_name>/
  analysis.json           # Full beat/phrase analysis
  metadata.json           # Composition data + Resolume mapping
  clips/                  # One clip per phrase
  loops/                  # Beat-quantized seamless loops
  resolume/               # Resolume-organized export (after deck export)
    Layer1_Drops/
    Layer2_Buildups/
    Layer3_Breakdowns/
    Layer4_Ambient/
    deck_info.json        # BPM, layer descriptions, import instructions
```

### Layer Mapping

| Layer | Content | Blend Mode | Phrase Types |
|-------|---------|------------|--------------|
| Layer 1 | Drops | Add | drop |
| Layer 2 | Buildups | Screen | buildup |
| Layer 3 | Breakdowns | Screen | breakdown |
| Layer 4 | Ambient | Multiply | intro, outro |

### BPM Sync

All clips are designed to loop at the track's BPM. In Resolume:

1. Set **Composition > BPM** to the value in `deck_info.json`
2. For each clip: **Clip > Transport > BPM Sync**
3. Set clip trigger mode to **Column** for synchronized layer switching

### OSC Control

The generated OSC trigger script sends messages to Resolume's OSC listener (default port 7000):

```bash
# Run alongside your track playback
python osc_trigger.py

# Target a remote Resolume instance
python osc_trigger.py --host 10.0.0.5 --port 7001

# Preview trigger timing without sending OSC
python osc_trigger.py --dry-run
```

OSC addresses used:
- `/composition/layers/{layer}/clips/{column}/connect` -- trigger clip
- `/composition/tempocontroller/tempo` -- set master BPM

## Roadmap

- **Resolume ALFC export** -- Direct export to Resolume's Advanced Composition format, skipping manual import
- **Real-time preview** -- Live preview window showing beat-synced visuals during generation
- **Video-to-video models** -- Use Stable Video Diffusion or similar for smoother inter-keyframe animation
- **Audio-reactive parameters** -- Map spectral features (bass, mids, highs) to Resolume effect parameters via OSC in real time
- **MIDI trigger support** -- Generate MIDI files for hardware controller mapping
- **Multi-track set builder** -- Build a full DJ set's worth of visuals with automatic BPM matching and transitions
- **GPU-accelerated effects** -- Use OpenGL/Vulkan shaders for real-time beat-sync effects instead of PIL frame-by-frame rendering

## License

MIT
