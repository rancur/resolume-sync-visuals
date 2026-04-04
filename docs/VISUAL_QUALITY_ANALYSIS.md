# Visual Quality Analysis — Post-Generation Review

**Date**: 2026-03-27
**Reviewer**: Internal review
**Videos reviewed**: 6 generated tracks (Kling v1.5 Pro, Will See brand)

---

## Executive Summary

After reviewing all 6 generated videos, we identified 7 fundamental issues that prevent the output from being usable as professional VJ content. The core problem is architectural: we built a **narrative video generator** (one continuous video per song) when we should have built a **VJ loop generator** (a set of beat-synced loops per phrase type). Professional VJ content is built from short, seamless, rhythmic loops — not linear 4-minute videos.

### Priority Ranking

| # | Issue | Impact | Cost Impact | Difficulty |
|---|-------|--------|-------------|------------|
| 1 | Beat sync (no rhythmic pulsing) | Critical | +$0 (ffmpeg) | Medium |
| 2 | One keyframe per segment, not per phrase | Critical | -50% cost | Easy |
| 3 | Loop architecture (narrative vs VJ loops) | Critical | -60% cost | Hard |
| 4 | Visuals don't contrast between sections | High | +$0 | Easy |
| 5 | All genres look the same | High | +$0 | Easy |
| 6 | Keyframe collage/grid artifacts | Medium | +5% cost | Easy |
| 7 | Metadata needs enrichment | Low | +$0 | Easy |

---

## Issue 1: Videos Don't Loop During Phrases — New Graphics Appear Mid-Phrase

### Symptom
A 38-second drop phrase gets split into 4 segments (each ~10s, the Kling max). Each segment gets a UNIQUE keyframe image from Flux LoRA. The visual identity changes every 10 seconds within what should be a unified visual phrase.

### Root Cause
In `src/pipeline.py`, method `_plan_segments()` (lines 591-638), when a phrase exceeds `max_segment_duration` (10s), it splits into sub-segments. Then in `generate_for_track()` (lines 298-310), each segment's keyframe decision is:

```python
if prev_frame_path and prev_frame_path.exists():
    # Use last frame from previous segment as starting point
    keyframe_path = prev_frame_path
else:
    keyframe_path = self._generate_keyframe(
        prompt=seg["prompt"],
        ...
    )
```

The **first segment** of a phrase generates a fresh keyframe. Subsequent segments within the same phrase use the **last frame** of the previous segment as their keyframe. This provides some continuity, but:

1. The first segment of each phrase ALWAYS generates a new keyframe — even if this phrase is the same type as the previous one.
2. Chaining via last-frame means visual drift accumulates: by segment 4, the visual has wandered far from the original keyframe.
3. The AI video model interprets each keyframe as a "starting scene" and generates new motion from it, compounding the drift.

### Fix
**Generate ONE keyframe per phrase, not per segment.** All segments within a phrase should animate from the same keyframe image.

- In `_plan_segments()`: add a `phrase_index` field to each segment so we know which segments belong to the same phrase.
- In `generate_for_track()`: generate ONE keyframe per unique phrase. For segments 2+ within a phrase, use the same keyframe (not the last frame of the previous segment).
- For visual continuity, the last-frame chaining should be an OPTION, not the default. Default should be same-keyframe looping.

### Cost Impact
**-50% keyframe generation cost.** A 4-minute song with 16 segments currently generates ~16 keyframes ($0.04 each = $0.64). With phrase-level keyframes, a typical song has 6-8 phrases, so ~7 keyframes ($0.28).

---

## Issue 2: Visuals Don't Change With Energy and Phrasing

### Symptom
A "drop" segment looks visually similar to a "breakdown" segment. The difference in audio energy (explosive drop vs calm breakdown) is not reflected in the visuals with enough contrast.

### Root Cause
The brand guide (`config/brands/will_see.yaml`) has distinct section prompts (lines 54-99), and the motion guidance differs per section. However:

1. **The brand base style dominates every prompt.** Every section starts with "chunky pixel art style, retro indie video game aesthetic..." (~200 characters of brand identity) before any section-specific content. The section-specific text is a small fraction of the total prompt.
2. **Motion guidance is in the prompt but AI video models mostly ignore text motion cues.** Kling animates based on what it "sees" in the keyframe image, not what the prompt says about motion.
3. **Energy modifiers are too subtle.** In `video_pipeline.py` `build_segment_prompt()` (lines 340-349), the energy modifier is just a short phrase like "maximum intensity, overwhelming visual power" vs "moderate energy, balanced motion" — these read similarly to a video model.

### Fix
1. **Dramatically differentiate section prompts at the IMAGE level.** Drops need: maximum color saturation, bright/explosive compositions, complex dense detail, bold shapes. Breakdowns need: desaturated colors, minimal elements, vast negative space, soft focus.
2. **Apply post-processing differentiation with ffmpeg.** After generation, drops get: contrast boost (+50%), saturation boost (+40%), slight speed increase (1.2x). Breakdowns get: desaturation (-30%), slight blur, slow speed (0.8x).
3. **Use different Flux LoRA scale per section.** Drops: LoRA scale 1.2 (stronger brand). Breakdowns: LoRA scale 0.6 (softer brand).
4. **Energy-based post-processing curve.** Map energy 0.0-1.0 to an ffmpeg filter chain: brightness, contrast, saturation, speed multiplier.

### Cost Impact
**+$0.** ffmpeg post-processing is free. Prompt changes are free.

---

## Issue 3: Each Video Looks Similar — Not Distinctive Enough Per Genre

### Symptom
A Dubstep track and a House track both look like "pixel art psychedelic greenhouse" because the Will See brand guide dominates the prompt.

### Root Cause
In `_build_prompt()` (lines 698-725 of `pipeline.py`), the prompt is assembled as:

```python
parts = [section_prompt]  # Brand section prompt (dominant, ~200 chars)
if content_modifier: parts.append(content_modifier)
if mood_colors: parts.append(mood_colors)
if mood_atmosphere: parts.append(mood_atmosphere)
if genre_extra: parts.append(genre_extra)  # Genre modifier (~50 chars)
if genre_pixel: parts.append(genre_pixel)  # Genre pixel style (~30 chars)
if genre_vocab_fragment: parts.append(genre_vocab_fragment)
if style_override: parts.append(style_override)
```

The brand section prompt is FIRST and LONGEST, giving it the most influence on the generation model. Genre modifiers are appended at the end and are much shorter. Flux/DALL-E weight tokens earlier in the prompt more heavily.

Additionally, the genre vocabulary files (`config/genres/*.yaml`) are loaded but only contribute a small `reference_styles` fragment to the prompt. The rich palette and motion data in those files is underutilized.

### Fix
1. **Restructure prompt priority: genre FIRST, brand SECOND.** For genre-specific content, the genre vocabulary should lead the prompt, with brand elements as a "style layer" on top.
2. **Create a genre-dominant prompt builder.** New prompt structure:
   - Genre visual vocabulary (environment, textures, motion) — 40% of prompt
   - Section energy/composition — 20% of prompt
   - Brand identity elements (eyes, pixel art, nature) — 20% of prompt
   - Mood/content modifiers — 20% of prompt
3. **Use genre-specific color palettes from config/genres/*.yaml** to influence the keyframe generation, not just as text.
4. **Add a `genre_weight` parameter** (0.0-1.0, default 0.6) to control how much genre vs brand dominates the visual.

### Cost Impact
**+$0.** Prompt restructuring is free.

---

## Issue 4: Keyframe Collage/Grid Artifacts

### Symptom
Sometimes the Flux LoRA keyframe comes back as a collage/grid of multiple images instead of a single continuous scene. When Kling then tries to animate a 2x2 grid of images, it produces weird motion artifacts.

### Root Cause
DALL-E 3 and Flux can interpret prompts that mention multiple distinct elements as a request for a "reference sheet" or "collage layout." The Will See brand guide has prompts like "eyes peeking from between leaves and flowers" which can be interpreted as multiple distinct vignettes.

There is no validation of the generated keyframe before it's passed to the video model.

### Fix
1. **Add anti-collage directives to ALL keyframe prompts.** Append: `"single continuous scene, one unified composition, no collage, no grid, no multiple panels, no split screen, no reference sheet"`.
2. **Add keyframe validation.** After generation, analyze the image for grid-like patterns:
   - Check for strong vertical/horizontal edge lines at 1/2, 1/3, 1/4 positions
   - Use simple edge detection (PIL/Pillow) to find dominant grid lines
   - If grid detected, regenerate with stronger anti-collage prompt
3. **Limit regeneration attempts** to 2 retries to avoid runaway costs.

### Cost Impact
**+5% cost** from occasional regeneration. But prevents wasted $0.75 video generation calls on bad keyframes, so net savings.

---

## Issue 5: Doesn't Hit With the Beat

### Symptom
The AI video plays at constant motion regardless of BPM. At 128 BPM (beat every 0.47s), nothing visual happens on beat boundaries. The video feels disconnected from the music.

### Root Cause
This is the fundamental limitation of current AI video models. Kling, Runway, Minimax — none of them understand musical timing. They generate smooth, continuous motion at whatever pace the model decides. There is NO beat-level input to these models.

The codebase has beat-sync effects in `src/generator/engine.py` (the image-based pipeline) via `apply_beat_sync_effects()`, but the video pipeline in `src/pipeline.py` does NOT apply any post-processing beat effects. The generated video goes straight from Kling output to crossfade stitching to DXV encoding.

### Fix — Three-Layer Approach

**Layer 1: Post-processing beat effects (ffmpeg)**
After each segment is generated, apply beat-synced effects:
- **Brightness flash** on every beat (brief +30% brightness spike, 2 frames)
- **Zoom pulse** on every bar (slight 1.02x zoom on beat 1 of each bar, 4 frames)
- **Color shift** on phrase boundaries (hue rotate 15 degrees)
- **Speed ramping** for buildups (gradually accelerate from 0.8x to 1.2x)

Implementation: Generate a beat map from BPM, then build an ffmpeg filter chain with `eq` (brightness), `zoompan` (zoom), and `hue` (color) filters keyed to frame numbers.

**Layer 2: Resolume BPM transport**
Configure clips in Resolume with BPM Sync transport mode. Resolume's BPM engine will loop clips in time with the DJ's master BPM. This handles global sync — our post-processing handles per-beat visual accents.

**Layer 3: Generate beat-length loops**
Instead of 10-second segments, generate 2-bar loops (at 128 BPM = 3.75s). These naturally loop on beat boundaries. More on this in Issue 7.

### Cost Impact
- Layer 1: **+$0** (ffmpeg post-processing)
- Layer 2: **+$0** (Resolume configuration)
- Layer 3: **-40% cost** (shorter loops = fewer seconds of video generation)

---

## Issue 6: Metadata Could Be Better

### Symptom
The current `track_metadata.json` saved per track has basic info (title, artist, BPM, cost) but lacks the rich information needed for Resolume integration and debugging.

### Root Cause
The metadata dict in `generate_for_track()` (lines 401-418 of `pipeline.py`) is minimal:
```python
metadata = {
    "title": title, "artist": artist, "bpm": bpm,
    "nas_path": nas_final, "segments": len(segment_videos),
    ...
}
```

Missing: phrase timeline with timestamps, per-segment keyframe descriptions, energy curve, stem analysis summary, mood details, generation parameters, per-segment costs, keyframe image paths.

### Fix
Enrich the metadata with:
```json
{
  "phrase_timeline": [
    {"start": 0.0, "end": 16.0, "label": "intro", "energy": 0.2},
    {"start": 16.0, "end": 48.0, "label": "buildup", "energy": 0.5},
    ...
  ],
  "segments": [
    {
      "index": 0,
      "start": 0.0,
      "end": 10.0,
      "label": "intro",
      "phrase_index": 0,
      "keyframe_prompt": "...",
      "motion_prompt": "...",
      "keyframe_path": "keyframe_000.png",
      "video_path": "segment_000.mp4",
      "cost_usd": 0.78,
      "model": "kling-v1-5-pro",
      "generation_time_s": 45.2
    }
  ],
  "energy_curve": [[0.0, 0.2], [16.0, 0.5], [48.0, 0.9], ...],
  "stems_summary": {
    "has_vocals": false,
    "dominant_instruments": ["drums", "bass", "synth"],
    "bass_drop_times": [48.0, 112.0]
  },
  "mood": {"quadrant": "euphoric", "valence": 0.7, "arousal": 0.8},
  "generation": {
    "brand": "will_see",
    "video_model": "kling-v1-5-pro",
    "image_model": "flux-lora",
    "total_cost_usd": 12.50,
    "total_generation_time_s": 340,
    "generated_at": "2026-03-27T12:00:00Z"
  }
}
```

### Cost Impact
**+$0.** Just saving more data we already have.

---

## Issue 7: Visuals Could Be More Like DJ Loops — Architecture Rethink

### Symptom
We generate one continuous 4-minute video per song. Professional VJ content is a SET of short, seamless, rhythmic LOOPS — one per phrase type. Resolume then triggers the right loop for each section.

### Root Cause
The entire pipeline is designed for linear video:
1. `_plan_segments()` creates a linear sequence of segments covering the full song duration
2. `generate_for_track()` generates each segment sequentially, chaining via last-frame extraction
3. `stitch_videos()` concatenates all segments into one continuous video
4. The output is a single `.mov` file pushed to NAS

This is the wrong architecture for VJ content. Professional VJs use:
- **Loop banks**: A set of 4-8 bar seamless loops per visual theme
- **Phrase-type loops**: One loop for drops, one for breakdowns, one for buildups, etc.
- **BPM-synced playback**: Resolume loops clips at the master BPM
- **Manual triggering**: The VJ triggers clips in response to the DJ's transitions

### Fix — VJ Loop Architecture

**Replace the linear pipeline with a loop-bank pipeline:**

1. **Analyze song** (same as now — phrases, mood, BPM, stems)
2. **Identify unique phrase types** (typically 3-5: intro, buildup, drop, breakdown, outro)
3. **For each phrase type, generate a SET of loops:**
   - 1 hero loop (4 bars, highest quality)
   - 1-2 variation loops (4 bars, standard quality)
   - 1 transition loop (2 bars, for phrase boundaries)
4. **Loop duration = exactly N bars** at the song's BPM:
   - At 128 BPM: 4 bars = 7.5s (fits in Kling's 10s max)
   - At 174 BPM (DnB): 4 bars = 5.5s (fits in Kling's 10s max)
5. **Apply beat-sync post-processing** to each loop
6. **Output structure per song:**
   ```
   /Songs/<track>/
     loops/
       drop_hero.mov        (4 bars, DXV, seamless loop)
       drop_var_01.mov      (4 bars, DXV, variation)
       breakdown_hero.mov   (4 bars, DXV, seamless loop)
       buildup_hero.mov     (4 bars, DXV, seamless loop)
       intro_hero.mov       (4 bars, DXV, seamless loop)
     timeline.json          (phrase map for auto-trigger)
     metadata.json          (full enriched metadata)
   ```
7. **Resolume composition** maps loops to layers/columns with BPM sync transport
8. **Timeline JSON** enables automated clip triggering in Resolume via OSC

### Cost Comparison

**Current approach (linear):**
- 4-minute song at 128 BPM
- ~24 segments of 10s each
- 24 keyframes ($0.04 x 24 = $0.96)
- 24 video generations ($0.75 x 24 = $18.00)
- **Total: ~$19/song**

**Loop-bank approach:**
- 5 phrase types x 2 loops each = 10 loops
- 10 keyframes ($0.04 x 10 = $0.40)
- 10 video generations ($0.75 x 10 = $7.50)
- **Total: ~$8/song (58% savings)**

### Quality Impact
- **Much better.** Short loops are what AI video models do best (no drift, no narrative needed)
- **Seamless looping** is achievable with 4-bar clips (vs impossible with 4-minute videos)
- **Beat sync** is more effective on short loops (less accumulation of timing errors)
- **Resolume integration** is native (loops are what Resolume is designed for)

---

## Professional VJ Content Creation Comparison

| Aspect | Our Current Approach | Professional VJ Approach |
|--------|---------------------|--------------------------|
| Format | One continuous video per song | Set of short seamless loops |
| Duration | 3-5 minutes linear | 4-8 bar loops (5-10 seconds) |
| Beat sync | None | BPM transport in Resolume |
| Triggering | Auto-play with song | Manual or MIDI-triggered |
| Section contrast | Subtle prompt differences | Completely different loops per section |
| Visual consistency | Drifts over time | Seamless within each loop |
| Resolume integration | Single clip per song | Multi-layer loop bank |
| Cost per song | ~$19 | ~$8 |

---

## Implementation Roadmap

### Phase 1: Quick Wins (Issues 2, 3, 4, 6) — 1-2 days
- Restructure prompts for section contrast and genre dominance
- Add anti-collage directives to keyframe prompts
- Add keyframe grid validation
- Enrich metadata output
- **No architectural changes. Immediate quality improvement.**

### Phase 2: Beat Sync Post-Processing (Issue 5, Layer 1) — 2-3 days
- Build ffmpeg beat-sync filter chain
- Brightness flash on beats, zoom pulse on bars
- Energy-based post-processing curve
- **Works with current architecture.**

### Phase 3: Phrase-Level Keyframes (Issue 1) — 1-2 days
- Track phrase_index through segment planning
- Generate one keyframe per phrase
- All sub-segments within a phrase use the same keyframe
- **50% reduction in keyframe costs.**

### Phase 4: VJ Loop Architecture (Issues 5 Layer 3, 7) — 1 week
- New loop-bank pipeline alongside existing linear pipeline
- Generate N-bar seamless loops per phrase type
- Resolume composition builder for loop banks
- Timeline JSON for OSC auto-triggering
- **Complete architectural shift. Maximum quality improvement.**

---

## GitHub Issues Created

- #78: Phase-level keyframes: one keyframe per phrase, not per segment
- #79: Extreme section contrast: make drops EXPLODE, breakdowns BREATHE
- #80: Genre-dominant prompts: genre drives visuals, brand is a layer
- #81: Keyframe validation: detect and reject collage/grid artifacts
- #82: Beat-sync post-processing: ffmpeg brightness/zoom on beats
- #83: Rich metadata: phrase timeline, energy curve, per-segment details
- #84: VJ loop-bank architecture: generate loop sets instead of linear video
