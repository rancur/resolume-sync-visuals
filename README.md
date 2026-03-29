# Resolume Sync Visuals

Generate full-length AI videos for every song in your DJ library, perfectly synced to Resolume Arena via Denon timecode transport. The pipeline connects to [Lexicon DJ](https://lexicondj.com/) to pull your music library with DJ-verified BPM/key/genre/energy metadata, analyzes each track's structure (intro, buildup, drop, breakdown, outro) and mood, generates AI video segments using Kling, Minimax, or Runway, chains them into a single video matching the song's exact duration, encodes to DXV for GPU-accelerated Resolume playback, pushes everything to NAS, and builds one `.avc` composition where every clip auto-triggers when you load the matching track on your Denon SC6000. All visuals are styled by a personal brand guide -- your visual identity baked into every frame.

**74 Python files | 22,000 lines | 594 tests passing | 26 commits**

---

## Quick Start

The three commands that do everything:

```bash
# 1. Verify Lexicon is reachable
rsv lexicon connect

# 2. Generate a video for one track using your brand guide
rsv lexicon generate "Track Title" --brand will_see

# 3. Generate videos for your entire library and build the Resolume composition
rsv lexicon show --brand will_see
```

---

## Architecture

```
Lexicon DJ API (BPM, key, genre, energy, happiness)
         |
         v
  +------+-------+
  |  NAS (SSH)   |  <-- Audio files live on Synology NAS
  +------+-------+
         |
         v
  +------+-------+
  |   Analyzer   |  librosa BPM/beats/phrases + Essentia mood
  +------+-------+  (happy/sad/aggressive/relaxed/party)
         |
         v
  +------+-------+
  | Brand Guide  |  config/brands/<name>.yaml
  +------+-------+  Per-section prompts, mood/genre modifiers, LoRA weights
         |
         v
  +------+-------+
  |  Flux LoRA   |  fal.ai -- keyframe image per song section
  +------+-------+  Trained on your brand aesthetic
         |
         v
  +------+-------+
  |  Kling i2v   |  fal.ai -- animate each keyframe into video
  +------+-------+  Last-frame chaining for visual continuity
         |
         v
  +------+-------+
  |   Encoder    |  ffmpeg -- stitch, crossfade, trim to exact duration
  +------+-------+  DXV (dxt1) or HAP Q encoding for Resolume
         |
         v
  +------+-------+
  |     NAS      |  /volume1/vj-content/<track>/
  +------+-------+
         |
         v
  +------+--------+
  | Resolume .avc |  Denon transport mode -- auto-switches visuals
  +------+--------+  when DJ loads a track on SC6000
         |
         v
  +------+--------+
  | StagelinQ     |  Real-time deck state from Denon hardware
  +---------------+  UDP 51337 discovery, TCP state streaming
```

---

## Features

### Pipeline
- **Lexicon DJ integration** -- pulls DJ-verified BPM, key, genre, energy, happiness from Lexicon's local API
- **Full-song video generation** -- one continuous AI video per track, not loops or stills
- **Exact duration matching** -- video length matches audio to the frame via pad/trim/loop
- **Segment chaining** -- last frame of segment N becomes input for segment N+1, maintaining visual flow
- **Crossfade transitions** -- smooth xfade between song sections via ffmpeg filter graph
- **NAS integration** -- copies audio from NAS, pushes finished videos back, all via SSH

### Analysis
- **BPM and beat detection** -- librosa-powered with Lexicon BPM override when available
- **Phrase segmentation** -- auto-detects intro, buildup, drop, breakdown, outro
- **Mood analysis** -- Essentia models detect happy/sad/aggressive/relaxed/party, maps to Russell's circumplex (euphoric/tense/melancholic/serene)
- **Genre detection** -- auto-detects genre from audio features (BPM, spectral centroid, onset density, bass energy)
- **Energy envelope** -- per-beat energy curve drives visual intensity

### Generation
- **AI video models** -- Kling v1, Kling v1.5 Pro, Minimax, Runway Gen-3, Wan 2.1
- **AI keyframe images** -- Flux LoRA (fal.ai) with trained brand weights, or DALL-E 3
- **Professional VJ prompts** -- section-aware, mood-reactive, genre-specific prompt engineering with volumetric lighting, cinematic composition, and LED-wall-optimized contrast
- **10 style presets** -- abstract, cosmic, cyberpunk, fire, fractal, glitch, laser, liquid, minimal, nature
- **Brand guide system** -- YAML configs controlling every visual decision per section, mood, and genre

### Resolume Integration
- **DXV codec encoding** -- GPU-decoded native Resolume format (ffmpeg `-c:v dxv -format dxt1`)
- **HAP codec fallback** -- open standard, cross-platform GPU decoding
- **Denon transport mode** -- `.avc` composition where each clip is linked by track title to a Denon deck
- **Auto-visual switching** -- load a track on your SC6000 and Resolume triggers the matching video
- **StagelinQ listener** -- receives real-time BPM, track name, playback state from Denon hardware over the network
- **Engine DJ database reader** -- reads `m.db` SQLite from USB drives, SC6000 internal SSD, or macOS local library

### Operations
- **Cost tracking** -- SQLite-backed per-call logging with budget limits and session totals
- **Render registry** -- tracks every generated video with metadata
- **Progress tracking** -- persistent bulk progress with resume support
- **Run logging** -- full audit trail of every pipeline run
- **Validation** -- pre-flight checks on inputs, outputs, codecs, and dependencies
- **Music library scanner** -- reads ID3/FLAC/OGG/M4A tags via mutagen, plus Engine DJ and Rekordbox databases

---

## Brand Guide System

Brand guides control your entire visual identity. Each guide is a YAML file in `config/brands/` that defines:

| Section | Purpose |
|---------|---------|
| `style.base` | Core aesthetic keywords included in every prompt |
| `style.colors` | Hex color palette (primary, secondary, accent, psychedelic) |
| `style.recurring_elements` | Visual motifs that appear across all videos |
| `sections` | Per-section prompts and motion (intro/buildup/drop/breakdown/outro) |
| `mood_modifiers` | How visuals shift based on detected mood (euphoric/tense/melancholic/serene) |
| `genre_modifiers` | Genre-specific visual vocabulary |
| `lyrics` | How lyrics appear (font style, keyword-triggered visuals) |
| `output` | Resolution, FPS, codec |

### Create Your Own Brand

```bash
# Copy the template
cp config/brands/TEMPLATE.yaml config/brands/my_brand.yaml

# Edit with your aesthetic, then generate
rsv lexicon generate "Track Title" --brand my_brand
```

The included `will_see.yaml` brand demonstrates a full implementation: chunky pixel art video game worlds with psychedelic nature, eyes as a signature motif, and per-genre modifiers for DnB, dubstep, 140, house, and techno.

LoRA weights for consistent visual identity are loaded from `assets/<brand>_lora.json` when available.

---

## CLI Reference

### Core Commands

| Command | Description |
|---------|-------------|
| `rsv analyze <file>` | Analyze a track -- BPM, beats, phrases, structure labels |
| `rsv generate <file>` | Generate visuals for a single track |
| `rsv bulk <directory>` | Process all music files in a directory |
| `rsv watch <directory>` | Watch for new music and auto-generate visuals |
| `rsv scan <directory>` | Scan music library, show metadata from tags and DJ databases |
| `rsv styles` | List available visual style presets |
| `rsv check` | Verify environment (ffmpeg, API keys, dependencies) |
| `rsv validate <output_dir>` | Validate generated videos (codec, resolution, duration) |

### Lexicon Commands

| Command | Description |
|---------|-------------|
| `rsv lexicon connect` | Test Lexicon API connection |
| `rsv lexicon library` | Show library stats -- track count, genres, BPM range, playlists |
| `rsv lexicon generate <title>` | Generate video for one track from Lexicon library |
| `rsv lexicon show` | Generate videos for entire library + build `.avc` composition |
| `rsv lexicon composition` | Build `.avc` from already-generated videos |

### Batch Commands (OpenAI Batch API)

| Command | Description |
|---------|-------------|
| `rsv batch prepare <dir>` | Prepare a JSONL batch file for OpenAI Batch API |
| `rsv batch submit <jsonl>` | Submit batch to OpenAI |
| `rsv batch status <id>` | Check batch processing status |
| `rsv batch download <id>` | Download batch results |
| `rsv batch process <id>` | Process downloaded batch into final videos |
| `rsv batch list` | List all batches |

### Dashboard Commands

| Command | Description |
|---------|-------------|
| `rsv dashboard costs` | View API spend by day, model, and total |
| `rsv dashboard renders` | List all rendered videos with metadata |
| `rsv dashboard report` | Generate a full cost/render report |
| `rsv dashboard logs` | View run logs |
| `rsv dashboard reset` | Reset tracking databases |

### Other Commands

| Command | Description |
|---------|-------------|
| `rsv export-composition <dir>` | Export Resolume `.avc` composition from output directory |
| `rsv thumbnails <dir>` | Generate thumbnail contact sheet |
| `rsv preview <dir>` | Preview generated clips |
| `rsv info <dir>` | Show generation metadata for an output directory |

### Key Flags

| Flag | Applies To | Description |
|------|-----------|-------------|
| `--brand <name>` | `lexicon generate`, `lexicon show` | Brand guide name (e.g. `will_see`) |
| `--style <name>` | Most generate commands | Visual style preset or path to YAML |
| `--quality <level>` | Most generate commands | `draft`, `standard`, or `high` |
| `--dry-run` | `lexicon generate` | Plan segments without generating |
| `--budget <usd>` | Global | Set API spend limit for the session |
| `--verbose` | Global | Enable debug logging |
| `--config <path>` | Global | Path to custom YAML config file |

---

## Technical Stack

### AI Models

| Model | Provider | Use | Max Duration | Cost/sec |
|-------|----------|-----|-------------|----------|
| Flux LoRA | fal.ai | Keyframe image generation (with brand LoRA weights) | -- | ~$0.003/image |
| Kling v1 | fal.ai | Image-to-video animation | 10s | ~$0.10 |
| Kling v1.5 Pro | fal.ai | Image-to-video animation (higher quality) | 10s | ~$0.15 |
| Minimax Video-01 | fal.ai | Image-to-video animation (budget) | 6s | ~$0.04 |
| Runway Gen-3 Alpha | Replicate | Image-to-video animation | 10s | ~$0.10 |
| Wan 2.1 | Replicate | Image-to-video animation (budget) | 5s | ~$0.05 |
| DALL-E 3 | OpenAI | Keyframe generation (no LoRA) | -- | $0.04-0.08/image |

### Video Codecs

| Codec | Format | Decoding | Use Case |
|-------|--------|----------|----------|
| DXV (dxt1) | `.mov` | GPU (Resolume native) | Primary -- best Resolume performance |
| HAP Q | `.mov` | GPU (open standard) | Fallback -- cross-platform |
| ProRes 422 | `.mov` | CPU | Fallback when HAP unavailable |
| H.264 | `.mp4` | CPU | Intermediate / preview |

### Protocols

| Protocol | Purpose |
|----------|---------|
| Lexicon REST API | Track metadata (BPM, key, genre, energy, happiness) on port 48624 |
| StagelinQ | Real-time Denon deck state (UDP 51337 discovery, TCP data) |
| Engine DJ SQLite | Offline track/crate data from `m.db` database |
| SSH (port 7844) | NAS file transfer (audio in, video out) |
| OSC | Resolume clip triggering (port 7000) |

### Analysis Libraries

| Library | Purpose |
|---------|---------|
| librosa | BPM detection, beat tracking, phrase segmentation, spectral features |
| Essentia | Mood classification (happy/sad/aggressive/relaxed/party via Discogs-EffNet) |
| mutagen | ID3/FLAC/OGG/M4A metadata reading |
| soundfile | Audio file I/O |

---

## Cost Estimates

Costs depend on the video model and song length. For a typical 4-minute track with 8 segments:

| Model | Per Track | 100-Track Library | Notes |
|-------|----------|-------------------|-------|
| Kling v1.5 Pro | ~$6-8 | ~$600-800 | Highest quality |
| Kling v1 | ~$4-5 | ~$400-500 | Good balance |
| Minimax | ~$1-2 | ~$100-200 | Budget option |
| Wan 2.1 | ~$1-2 | ~$100-200 | Budget option |

Plus ~$0.30-0.60 per track for Flux LoRA keyframe images (one per segment).

Use `rsv dashboard costs` to monitor spend in real time. Set `--budget` to cap session spend.

---

## Setup

### Prerequisites

- **Python 3.9+**
- **ffmpeg** with DXV codec support (must be on PATH)
- **Lexicon DJ** running with API enabled (Settings > Integrations)
- **1Password CLI** (`op`) for API key management (optional -- can use env vars)

### Installation

```bash
git clone https://github.com/willcurran/resolume-sync-visuals.git
cd resolume-sync-visuals

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

# Verify
rsv check
```

### API Keys

Set via environment variables or 1Password:

```bash
# fal.ai (Flux LoRA keyframes + Kling video generation)
export FAL_KEY="..."

# OpenAI (DALL-E 3 keyframes, Batch API)
export OPENAI_API_KEY="sk-..."

# Replicate (Runway, Wan 2.1)
export REPLICATE_API_TOKEN="r8_..."
```

With 1Password, keys are loaded automatically from the `OpenClaw` vault at runtime.

### NAS Setup

The pipeline expects a Synology NAS accessible via SSH on port 7844. Audio files are read from `/volume1/music/` and generated videos are pushed to `/volume1/vj-content/`. Configure connection details in `src/lexicon.py`.

### Resolume Setup

1. Import the generated `.avc` composition into Resolume Arena
2. Each clip is set to **Denon transport mode** with `denonTrackName` matching the track's ID3 title
3. Connect your Denon SC6000 to the same network
4. Load a track on the deck -- Resolume auto-triggers the matching visual

---

## Project Structure

```
src/
  cli.py                    CLI entry point (rsv command)
  pipeline.py               Turnkey Lexicon-to-Resolume pipeline
  lexicon.py                Lexicon DJ API client + NAS file operations
  nas.py                    NAS SSH file transfer (audio in, video out)
  scanner.py                Music library scanner (mutagen tags)
  encoder.py                DXV/HAP encoding, stitching, frame extraction
  validation.py             Input/output validation
  bulk_processor.py         Concurrent bulk processing engine
  watcher.py                File watcher for auto-generation
  analyzer/
    audio.py                BPM, beats, phrases, energy envelope
    mood.py                 Essentia mood analysis (Russell's circumplex)
    genre.py                Genre auto-detection and style mapping
    features.py             Extended feature extraction for visual mapping
    lyrics.py               Lyrics/title analysis (Genius API, Whisper)
    sonic_mapper.py         Sonic event detection and visual mapping
    stems.py                Demucs stem separation
  generator/
    video_pipeline.py       AI video generation orchestrator
    video_models.py         Multi-model support (Kling, Minimax, Runway, Wan)
    prompts.py              Professional VJ prompt engineering
    engine.py               Generation engine (keyframe + animation)
    batch.py                OpenAI Batch API support
    mood_visuals.py         Mood-to-visual parameter mapping
  composer/
    timeline.py             Timeline composition
    montage.py              Montage builder
    thumbnails.py           Contact sheet generator
  resolume/
    show.py                 .avc composition builder (BPM sync + Denon transport)
    composition.py          Resolume composition XML builder
    api.py                  Resolume REST API client
    export.py               Resolume deck export + OSC scripts
  denon/
    engine_db.py            Engine DJ SQLite database reader
    stagelinq.py            StagelinQ protocol listener
  tracking/
    costs.py                API cost tracking (SQLite)
    registry.py             Render registry
    progress.py             Bulk progress tracking
    run_log.py              Run audit logging
config/
  brands/                   Visual branding guides
    will_see.yaml           "Will See" brand (pixel art + psychedelic nature)
    TEMPLATE.yaml           Blank template for new brands
  styles/                   Visual style presets
docs/
  RESEARCH.md               Technical research on VJ content + AI video
```

---

## License

MIT
