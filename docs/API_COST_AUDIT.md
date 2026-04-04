# fal.ai API Cost Audit

**Date**: 2026-03-27
**Auditor**: Claude Code

## Summary of All fal.ai API Calls

| # | Location | Model | Cost/Call | Purpose | Frequency |
|---|----------|-------|-----------|---------|-----------|
| 1 | `server/routers/system.py` `/api/system/credits` | ~~`fal-ai/flux/schnell`~~ HTTP auth check | ~~$0.003~~ **$0.00** | Credit/key validation | Every 5 min (was 60s) |
| 2 | `src/pipeline.py` `_generate_keyframe()` | `fal-ai/flux-lora` | ~$0.04 | Keyframe image generation | Per segment |
| 3 | `src/pipeline.py` `_fal_image_to_video()` | `fal-ai/kling-video/v1.5/pro/image-to-video` | $0.75 | Animate keyframe to video | Per segment chunk |
| 4 | `src/generator/video_pipeline.py` `_animate_keyframe_fal()` | Various (Kling/Veo/Wan/etc) | $0.10-$4.00 | Animate keyframe to video | Per segment |
| 5 | `src/generator/engine.py` `_generate_image_openai()` | DALL-E 3 (OpenAI) | $0.08 | Keyframe generation (alt backend) | Per phrase keyframe |
| 6 | `scripts/generate_mind_control.py` | `fal-ai/imagen3` + `fal-ai/veo2/image-to-video` | $0.04 + $4.00 | Keyframe + animation | Per segment chunk |
| 7 | `scripts/generate_all_songs.py` | `fal-ai/imagen3` or DALL-E 3 + Kling/Veo2 | $0.04-0.08 + $0.75-$4.00 | Keyframe + animation | Per segment chunk |

## Waste Points Found and Fixed

### 1. CRITICAL: Credit Check Burning $4.32/day (FIXED)

**File**: `server/routers/system.py` + `web/src/hooks/useCredits.ts`

**Problem**: The `/api/system/credits` endpoint ran a Flux Schnell generation ($0.003) every 60 seconds to test if credits are active. The frontend polled this every 60s.

- Cost: $0.003 x 1440 calls/day = **$4.32/day = $129.60/month** for health checks alone
- This ran even when no generation was happening

**Fix applied**:
1. Replaced Flux Schnell generation with a **free HTTP auth check** against fal.ai's queue API (`GET /requests`). This validates the API key without running any model inference -- cost: **$0.00**.
2. Increased frontend polling interval from 60s to **5 minutes** (300s).
3. Increased server-side cache TTL from 60s to **5 minutes** (300s).

**Savings**: **$129.60/month**

### 2. CRITICAL: generate_all_songs.py Had No Resume Support (FIXED)

**File**: `scripts/generate_all_songs.py`

**Problem**: Unlike `generate_mind_control.py` which checks if segment video files already exist before regenerating, `generate_all_songs.py` had **zero resume/cache support**. Re-running the script (e.g., after a crash, network timeout, or partial failure) would regenerate every segment from scratch.

For a typical song with 10 segments and 2 chunks each:
- 20 x $0.75 (Kling) = **$15.00 wasted per re-run**
- With Veo 2: 20 x $4.00 = **$80.00 wasted per re-run**

**Fix applied**: Added segment-level file existence check (same pattern as `generate_mind_control.py`). If the output `.mp4` exists and is > 10KB, skip regeneration and extract last frame for continuity.

**Savings**: $15-$80 per interrupted/re-run batch

### 3. MODERATE: pipeline.py Keyframes Had No File Cache Check (FIXED)

**File**: `src/pipeline.py` `_generate_keyframe()`

**Problem**: The `_generate_keyframe()` method always called fal.ai Flux LoRA even when the output file already existed on disk. The `generator/engine.py` has render registry deduplication, but `pipeline.py`'s FullSongPipeline path did not check for existing files.

- Cost per unnecessary keyframe: ~$0.04
- For a 15-segment song: $0.60 wasted per re-run

**Fix applied**: Added file existence check at the top of `_generate_keyframe()`. If `output_path` exists and is > 1KB, return immediately.

### 4. MODERATE: pipeline.py Video Segments Had No File Cache Check (FIXED)

**File**: `src/pipeline.py` `_fal_image_to_video()`

**Problem**: The `_fal_image_to_video()` method always called fal.ai even when the output video already existed. Same issue as keyframes but much more expensive.

- Cost per unnecessary Kling call: $0.75
- Cost per unnecessary Veo 2 call: $4.00

**Fix applied**: Added file existence check at the top of `_fal_image_to_video()`. If `output_path` exists and is > 10KB, return immediately.

### 5. LOW RISK: Chunk Splitting Multiplies Costs (No Change Needed)

**Files**: `src/pipeline.py`, `scripts/generate_mind_control.py`, `scripts/generate_all_songs.py`

**Observation**: Segments longer than the model's max duration (8s for Veo 2, 10s for Kling) are split into sub-chunks, each requiring a separate API call. A 25-second segment = 3 Kling calls ($2.25) or 4 Veo 2 calls ($16.00).

**Assessment**: This is inherent to the models' limitations and the architecture is correct. The chunk splitting is necessary for long segments. The key optimization is to use Kling ($0.75) instead of Veo 2 ($4.00) as primary, which `generate_all_songs.py` already does (`using_veo2 = False`).

### 6. LOW RISK: Retry Logic (No Change Needed)

**File**: `src/generator/engine.py`

**Observation**: The retry logic for DALL-E 3 retries up to 5 times with exponential backoff. Each retry IS a new API call and IS charged.

**Assessment**: This is acceptable -- retries are necessary for transient failures (rate limits, server errors). The 5-retry limit is reasonable. The content policy retry simplifies the prompt, which is the right approach. fal.ai calls in pipeline.py and video_pipeline.py do NOT have retry logic, so a failure = 1 charge only.

### 7. INFO: Existing Caching Systems (Working Correctly)

The codebase has three layers of caching that ARE working:

1. **Render Registry** (`src/tracking/registry.py`): SQLite-based deduplication by audio hash + style + quality + phrase index. Used by `src/generator/engine.py`. Correctly skips re-renders.

2. **Keyframe Cache** (`src/generator/cache.py`): SHA-256 prompt-based cache for keyframe images and video segments. Used by `src/generator/engine.py`. Correctly avoids duplicate API calls.

3. **NAS existence check** (`src/pipeline.py:176`): `FullSongPipeline.generate_for_track()` checks if the final video already exists on NAS before starting any generation.

## Model Cost Reference

| Model | Type | Cost | Notes |
|-------|------|------|-------|
| `fal-ai/flux/schnell` | Image gen | $0.003 | Cheapest image model |
| `fal-ai/flux-lora` | Image gen | ~$0.04 | Used for brand keyframes |
| `fal-ai/imagen3` | Image gen | $0.04 | Google Imagen 3 |
| `fal-ai/imagen3/fast` | Image gen | $0.02 | Faster, slightly lower quality |
| DALL-E 3 (OpenAI) | Image gen | $0.08 | Fallback keyframe model |
| `fal-ai/kling-video/v1.5/pro/image-to-video` | I2V | $0.75 | Primary animation model |
| `fal-ai/kling-video/v2/master/image-to-video` | I2V | $1.00 | Higher quality |
| `fal-ai/veo2/image-to-video` | I2V | $4.00 | Highest quality, expensive |
| `fal-ai/veo3/fast/image-to-video` | I2V | $2.00 | Fast Veo 3 |
| `fal-ai/wan/v2.1/image-to-video/480p` | I2V | $0.10 | Cheapest video model |
| `fal-ai/minimax/video-01/image-to-video` | I2V | $0.50 | Mid-range |
| `fal-ai/runway-gen3/turbo/image-to-video` | I2V | $0.50 | Fast turbo |
| `fal-ai/luma-dream-machine/ray-2/image-to-video` | I2V | $0.50 | Dream Machine |

## Total Estimated Monthly Savings

| Fix | Monthly Savings |
|-----|----------------|
| Credit check (was $4.32/day) | **$129.60** |
| Resume support in generate_all_songs.py | **$15-$80 per re-run** |
| Keyframe file caching in pipeline.py | **$0.60 per re-run** |
| Video segment caching in pipeline.py | **$7.50-$40 per re-run** |

The credit check fix alone saves **$129.60/month** guaranteed. The other fixes save money proportional to how often scripts are re-run or crash mid-generation.
