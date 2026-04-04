# Research: Professional VJ Content & AI Video Generation

## Architecture: Full-Song Video Pipeline

### The Workflow
```
Lexicon DJ (track metadata)
    │
    ▼
Audio Analysis (BPM, phrases, mood)
    │
    ▼
Segment Planning (intro → buildup → drop → breakdown → outro)
    │
    ▼
Keyframe Generation (DALL-E 3 / Flux — one image per segment)
    │
    ▼
Video Generation (Kling / Runway / Minimax — animate each keyframe)
    │
    ▼
Segment Chaining (last frame → next segment's input)
    │
    ▼
Video Assembly (ffmpeg stitch + crossfade to exact audio duration)
    │
    ▼
DXV Encoding (60fps 1080p, Resolume-native codec)
    │
    ▼
Named to match ID3 title → NAS vj-content/
    │
    ▼
Resolume Composition (Denon transport mode, auto-triggers on track load)
```

### Key Constraint
Video MUST be exactly the same duration as audio. Resolume ejects the clip
if the video ends before the audio track is over.

## Resolume + StagelinQ Integration

### How It Works
1. Denon SC6000 broadcasts track info via StagelinQ (UDP 51337 discovery → TCP StateMap)
2. Resolume receives track name, playback position, fader state
3. Resolume matches track name to a clip's `denonTrackName` property
4. Clip auto-triggers, video playhead locks to audio playhead frame-by-frame
5. DJ scratches, loops, cues — video follows everything via timecode sync

### Critical Details
- Transport mode must be **"Denon"** (not BPM Sync)
- Track matching uses **ID3 title tag** (falls back to filename)
- Video and audio must be **same duration**
- Encode as **DXV codec** (.mov) for GPU-decoded playback
- **60fps** minimum for LED walls
- Layer locks during Denon playback

### Resolume REST API
- Port 8080, `http://127.0.0.1:8080/api/v1`
- Can programmatically load clips, set transport, configure Denon linking
- WebSocket at `ws://127.0.0.1:8080/api/v1` for real-time state

## AI Video Models (Ranked by Quality, March 2026)

| Rank | Model | Resolution | Duration | Quality | Cost/sec |
|------|-------|-----------|----------|---------|----------|
| 1 | Veo 2 | 4K | 8s | 10/10 | $0.35-0.50 |
| 2 | Kling 3.0 Pro | 4K/60fps | 120s | 9/10 | $0.10 |
| 3 | Minimax Hailuo | 1080p | 6s | 8.5/10 | $0.04 |
| 4 | Sora 2 | 1080p | 20s | 8.5/10 | $0.30 |
| 5 | Runway Gen-4.5 | 1080p | 20s | 8/10 | $0.10 |
| 6 | Wan 2.1 | 1080p | 5s | 8/10 | $0.05 |

### Best for VJ Content
- **Kling**: Best value, 120s per generation, strong image-to-video
- **Runway**: Best for abstract/VFX aesthetics
- **Minimax**: Cheapest, smooth fluid motion

### API Access
- **fal.ai**: Hosts Kling, Minimax, Wan — fastest, recommended
- **Replicate**: Hosts Wan, Runway, community models
- **Direct APIs**: Kling (api.klingai.com), Runway (api.runwayml.com)

## Professional VJ Content Standards

### Technical Specs
- Resolution: 1080p minimum, 4K for LED walls
- Frame rate: 60fps for LED walls, 30fps minimum
- Codec: DXV3 (Resolume native) or HAP (cross-platform)
- File format: .MOV
- Alpha channel: Yes for layering

### What Makes Pro Content
1. Continuous fluid motion (not interpolated stills)
2. Consistent art direction across entire set
3. Volumetric lighting, depth of field
4. Intentional color grading
5. Rhythmic motion that works with music
6. Seamless looping (for loop content)

### Top VJ Content Creators
- Ghosteam (Deadmau5, Skrillex, Bad Bunny)
- Beeple (Cinema 4D + Octane, free resources)
- STVinMotion, LAAK, VJ Picles

### Tools Pros Use
- Cinema 4D + Octane (pre-rendered 3D)
- TouchDesigner (real-time generative)
- Notch (stadium-scale real-time 3D)
- After Effects (compositing)
- Resolume Arena (playback/mixing)

## Cost Estimates

### Per Song (4 minutes)
| Model | Segments | Cost |
|-------|----------|------|
| Kling 3.0 | 2 × 120s | $8-15 |
| Minimax | 8 × 30s | $4-8 |
| Runway | 4 × 60s | $12-20 |

### Full Library
| Tracks | Budget Range |
|--------|-------------|
| 10 | $80-150 |
| 100 | $800-1,500 |
| 500 | $4,000-7,500 |
