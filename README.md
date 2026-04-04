# Resolume Sync Visuals

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Generate AI-powered, beat-synced visuals for every song in your DJ library. Automatically.**

Resolume Sync Visuals analyzes your music library, detects song structure and mood, generates AI video loops styled to your brand, applies beat-synced post-processing, encodes to GPU-decoded DXV, and builds Resolume Arena compositions that auto-trigger visuals when you load a track on your Denon SC6000.

---

## Key Features

- **V2 Loop-Bank Architecture** -- 5-10 short loops per song (one per phrase type), looped to fill each section. 58% cost reduction vs linear segment generation with better visual rhythm.
- **Beat-Sync Post-Processing** -- brightness flash on every beat, zoom pulse on every bar, all tempo-locked to your track's BPM.
- **Phrase-Aligned Segments** -- visual changes land on drops, breakdowns, buildups, and transitions. The system detects song structure automatically.
- **14 AI Video Models** -- Kling v1/v1.5/v2, MiniMax, Veo 2/3, Wan 2.1, Runway Gen-3, Luma Ray2, Pika 2, CogVideoX with automatic fallback chains.
- **3 Image Models** -- DALL-E 3, Flux Schnell/LoRA, Google Imagen 3 for keyframe generation.
- **Stem Separation** -- Demucs-powered isolation of drums, bass, synths, and vocals for per-stem visual mapping.
- **Mood Analysis** -- Essentia AI detects happy/sad/aggressive/relaxed/party mood, mapped to Russell's circumplex model (euphoric/tense/melancholic/serene).
- **45 Genre Modifiers** -- curated visual vocabularies for bass music, house, techno, trance, DnB, breaks, ambient, 140, and dozens of sub-genres.
- **Brand Guide System** -- YAML configs define your entire visual identity: colors, motifs, per-section prompts, mood reactions, genre overrides.
- **DXV Encoding** -- GPU-decoded Resolume-native codec for zero-CPU playback.
- **Denon StagelinQ** -- auto-trigger visuals when loading tracks on SC6000 hardware.
- **Cost Protection** -- $30/song cap with automatic model downgrade to stay within budget.
- **Web Dashboard** -- 17-page React UI for library management, generation queue, timeline editing, cost tracking, and more.

---

## Quick Start (Docker)

```bash
# 1. Clone and configure
git clone https://github.com/your-username/resolume-sync-visuals.git
cd resolume-sync-visuals
cp .env.example .env
# Edit .env with your API keys and network settings

# 2. Build and start
docker compose build
docker compose up -d

# 3. Verify
curl http://localhost:8765/api/health
```

The container builds the React frontend, bundles the Python backend, and serves both on port 8765.

### Local Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
rsv check  # Verify dependencies
```

### Generate Your First Visual

```bash
# Connect to Lexicon DJ
rsv lexicon connect

# Generate a video for one track
rsv lexicon generate "Track Title" --brand example

# Generate for your entire library and build the Resolume composition
rsv lexicon show --brand example
```

---

## Configuration

### Brand Guides

Brand guides are the core of your visual identity. Each is a YAML file in `config/brands/` that controls:

| Section | Purpose |
|---------|---------|
| `style.base` | Core aesthetic keywords included in every prompt |
| `style.colors` | Hex color palette (primary, secondary, accent) |
| `style.recurring_elements` | Visual motifs for brand consistency |
| `sections` | Per-section prompts and motion (intro/buildup/drop/breakdown/outro) |
| `mood_modifiers` | Visual shifts based on detected mood |
| `genre_modifiers` | Genre-specific visual vocabulary |
| `lyrics` | Lyrics display style and keyword-triggered visuals |
| `output` | Resolution, FPS, codec |

#### Create Your Own Brand

```bash
cp config/brands/TEMPLATE.yaml config/brands/my_brand.yaml
# Edit with your aesthetic, then generate:
rsv lexicon generate "Track Title" --brand my_brand
```

LoRA weights for consistent visual identity can be loaded from `assets/<brand>_lora.json`.

### Environment Variables

Copy `.env.example` and set your API keys:

```bash
# Required: at least one image + one video provider
FAL_KEY=...              # fal.ai (Flux LoRA, Kling, MiniMax, Wan, etc.)
OPENAI_API_KEY=sk-...    # OpenAI (DALL-E 3, Batch API)
REPLICATE_API_TOKEN=r8_... # Replicate (alternative providers)

# Network
LEXICON_HOST=127.0.0.1   # Lexicon DJ local API
NAS_HOST=...              # NAS for audio/video storage (SSH)
RESOLUME_HOST=127.0.0.1   # Resolume REST API
```

---

## Architecture

```
Lexicon DJ API ──> BPM, key, genre, energy
       │
       ▼
   NAS (SSH) ──> Audio files
       │
       ▼
   Analyzer ──> BPM/beats/phrases (librosa)
       │        Mood (Essentia AI)
       │        Stems (Demucs)
       │        Genre detection
       ▼
  Brand Guide ──> config/brands/<name>.yaml
       │
       ▼
  Image Gen ──> Keyframe per phrase type (Flux LoRA / DALL-E 3 / Imagen 3)
       │
       ▼
  Video Gen ──> Animate each keyframe into a loop (Kling / MiniMax / Wan / etc.)
       │
       ▼
  Beat-Sync ──> Brightness flash on beat, zoom pulse on bar
       │
       ▼
   Encoder ──> Stitch, crossfade, DXV encode (ffmpeg)
       │
       ▼
  Resolume ──> .avc composition with Denon transport triggers
       │
       ▼
  StagelinQ ──> Auto-switch visuals on SC6000 deck load
```

### V2 Loop-Bank Pipeline

Instead of generating 24+ unique linear segments per song, the V2 architecture:

1. Analyzes phrases (intro, buildup, drop, breakdown, outro)
2. Groups consecutive same-type phrases
3. Generates **one keyframe** per unique phrase type
4. Animates **one short loop** per phrase type (2-4 bars at song BPM)
5. Loops each within its phrase duration
6. Adds beat-synced post-processing
7. Stitches all sections with crossfades

Result: 5-10 API calls instead of 24+, with rhythmic looping that actually looks better on a dance floor.

---

## Supported Models

### Video Models

| Model | Provider | Max Duration | Tier | Notes |
|-------|----------|-------------|------|-------|
| Kling v2 | fal.ai | 10s | Premium | Highest quality |
| Kling v1.5 Pro | fal.ai | 10s | Premium | Great detail |
| Veo 3 | fal.ai | 8s | Premium | Cinematic |
| Veo 2 | fal.ai | 8s | Premium | Cinematic |
| Runway Gen-3 | fal.ai | 10s | Quality | Fast turnaround |
| MiniMax | fal.ai | 6s | Standard | Good balance |
| MiniMax Live | fal.ai | 6s | Standard | Fast |
| Wan 2.1 (1080p) | fal.ai | 5s | Standard | Multiple resolutions |
| Wan 2.1 (720p) | fal.ai | 5s | Budget | Good value |
| Wan 2.1 (480p) | fal.ai | 5s | Budget | Cheapest Wan |
| Luma Ray2 | fal.ai | 9s | Budget | Dream-like quality |
| Pika 2 | fal.ai | 5s | Budget | Stylized |
| CogVideoX | fal.ai | 6s | Budget | Cheapest |

### Image Models

| Model | Provider | Use |
|-------|----------|-----|
| Flux LoRA | fal.ai | Brand-trained keyframes (primary) |
| Flux Schnell | fal.ai | Fast keyframe generation |
| DALL-E 3 | OpenAI | High-quality keyframes |
| Imagen 3 | fal.ai | Google's image model |

### Smart Model Routing

The system automatically selects models per section type:
- **Drops** get premium models (Kling v2, Kling v1.5 Pro)
- **Buildups** get balanced models (Kling v1)
- **Breakdowns** get smooth-motion models (MiniMax)
- **Intros/Outros** get cost-efficient models (Wan 2.1)

If a model fails or would exceed budget, the system auto-downgrades through a fallback chain.

---

## Web UI

The React dashboard (served at port 8765 in Docker) includes 17 pages:

| Page | Description |
|------|-------------|
| Dashboard | Overview, recent generations, system health |
| Library | Browse tracks, filter by genre/mood/energy |
| Track Detail | Per-track analysis: phrases, mood, energy curve, stems |
| Generation Queue | Active and queued generation jobs |
| Timeline Editor | Visual timeline of phrase segments per track |
| Model Selection | Compare and configure AI models |
| Brand Editor | Edit brand YAML with live preview |
| Presets | Style preset browser (abstract, cosmic, cyberpunk, etc.) |
| Genres | Genre vocabulary browser and customization |
| Setlists | Plan and generate visuals for entire sets |
| Budget Dashboard | Cost tracking by model, day, and song |
| Comparison Viewer | Side-by-side model output comparison |
| Logs | Generation logs and error tracking |
| OSC Control | Resolume OSC trigger testing |
| Resolume Settings | Composition and transport configuration |
| Settings | Global app configuration |
| Setup Wizard | First-run configuration guide |

---

## Cost Estimates

The V2 loop-bank architecture generates 5-10 loops per song instead of 24+ segments. Typical costs for a 4-minute track:

| Model Tier | Per Track | 100-Track Library |
|-----------|----------|-------------------|
| Premium (Kling v2, Veo) | $4-8 | $400-800 |
| Quality (Kling v1, Runway) | $2-5 | $200-500 |
| Standard (MiniMax) | $1-2 | $100-200 |
| Budget (Wan, CogVideoX) | $0.50-1 | $50-100 |

Plus ~$0.03-0.60 per track for keyframe images depending on model.

**Cost protection:** A $30/song hard cap prevents runaway spend. When approaching the cap, the system auto-downgrades to cheaper models. Use `rsv dashboard costs` or the Budget Dashboard page to monitor spend in real time.

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `rsv lexicon connect` | Test Lexicon API connection |
| `rsv lexicon generate <title>` | Generate video for one track |
| `rsv lexicon show` | Generate for entire library + build `.avc` |
| `rsv lexicon library` | Library stats (track count, genres, BPM range) |
| `rsv analyze <file>` | Analyze a track (BPM, beats, phrases, mood) |
| `rsv generate <file>` | Generate visuals for a single audio file |
| `rsv bulk <directory>` | Process all music files in a directory |
| `rsv styles` | List available style presets |
| `rsv dashboard costs` | View API spend breakdown |
| `rsv check` | Verify environment and dependencies |

Key flags: `--brand <name>`, `--style <name>`, `--quality draft|standard|high`, `--dry-run`, `--budget <usd>`

---

## Development

```bash
# Dev mode with hot reload
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
# Backend: http://localhost:8000
# Frontend: http://localhost:5173

# Run tests
pytest

# Auto-update (optional)
docker compose --profile auto-update up -d
```

---

## Contributing

Contributions are welcome. Please open an issue to discuss significant changes before submitting a PR.

---

## License

MIT
