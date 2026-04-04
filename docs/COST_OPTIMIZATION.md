# Cost Optimization: Scaling to 5,000 Tracks

## The Problem

Two songs cost $363 to generate. At that rate:
- 5,000 tracks x ~$180/track = **$900,000** -- completely impossible
- Even at the RESEARCH.md estimates of $8-15/track (Kling) = $40K-75K -- still way too much
- **Target: < $2/track = $10,000 total for the full library**

## Current Cost Breakdown (per 4-minute track)

| Component | Count | Unit Cost | Total |
|-----------|-------|-----------|-------|
| Keyframe images (Flux/DALL-E) | ~15 | $0.04 | $0.60 |
| Video segments (Kling v1.5 Pro) | ~15 x 10s | $1.50/seg | $22.50 |
| Lyrics analysis (OpenAI) | 1 | $0.10 | $0.10 |
| Stem separation (local) | 1 | $0.00 | $0.00 |
| **Total per track** | | | **~$23** |
| **Total for 5,000 tracks** | | | **$115,000** |

The video segments are 97% of the cost. Everything else is noise.

---

## Strategy 1: Fewer Segments Per Track (Looping)

**Concept:** Instead of generating unique video for every second, generate 5-8 unique
segments and loop them across matching phrases.

A typical 4-minute DnB track structure:
```
Intro (16 bars)  -> Buildup (8 bars) -> Drop (16 bars) -> Breakdown (16 bars) ->
Buildup (8 bars) -> Drop (16 bars)   -> Outro (16 bars)
```

Most sections repeat. Drop 1 and Drop 2 can share the same video. Buildup 1 and
Buildup 2 can share. That cuts 15 segments down to ~6 unique ones.

| Approach | Unique Segments | Cost/Track | 5,000 Tracks |
|----------|----------------|------------|--------------|
| Current (all unique) | 15 | $23.00 | $115,000 |
| Loop repeating sections | 6 | $9.60 | $48,000 |
| Aggressive looping (3 unique) | 3 | $5.10 | $25,500 |

**Implementation:** Modify `_plan_segments()` in `pipeline.py` to detect repeated
section types and reuse the first generated video for subsequent identical sections.
Add a `segment_reuse_map` that hashes (section_label + energy_bucket + mood) to
deduplicate within a single track.

**Difficulty:** Low -- purely pipeline logic, no new models needed.

---

## Strategy 2: Cross-Track Visual Library (Segment Sharing)

**Concept:** Two DnB tracks at 175 BPM with similar energy and mood could share drop
visuals. Build a content-addressable library of reusable video segments indexed by:
- Genre cluster (DnB, House, Techno, etc.)
- Energy bucket (low/mid/high)
- Section type (intro/buildup/drop/breakdown/outro)
- BPM range (120-130, 130-140, etc.)
- Mood quadrant (euphoric, dark, chill, aggressive)

**Math:** If the 5,000-track library has ~20 genre/energy/mood clusters, and each
cluster needs ~8 unique segments, that is:
- 20 clusters x 8 segments = 160 unique video segments
- 160 x $1.50/segment = **$240 total**
- Per track: **$0.05/track**

Even with 100 clusters (finer granularity): 800 segments = $1,200 total = $0.24/track.

**Tradeoff:** Visuals won't be unique per song. Two similar DnB tracks will look the
same. For a 5,000-track DJ library this is acceptable -- the audience never sees
back-to-back identical visuals because the DJ controls the mix.

**Implementation:**
1. Extend `KeyframeCache` in `cache.py` to index by (genre, energy, section, bpm_range, mood)
2. Before generating, query the library for a matching segment
3. If found, copy/link it; if not, generate and store
4. The `find_similar()` method already exists with Jaccard similarity -- upgrade to
   embedding-based similarity using the brand/genre/mood metadata

**Difficulty:** Medium -- needs a classification/clustering step before generation.

---

## Strategy 3: Image + FFmpeg Motion (No AI Video)

**Concept:** Generate only keyframe images (1 per section type) and use FFmpeg to
create motion from stills:
- Ken Burns (slow zoom + pan)
- Beat-synced zoom pulses
- Color cycling / hue rotation
- Crossfade dissolves between keyframes
- Strobe/flash on beat hits

**Cost:**
- 3-5 keyframe images per track x $0.04 = $0.12-0.20/track
- FFmpeg processing: free (local CPU)
- **Total: ~$0.20/track = $1,000 for 5,000 tracks**

**Quality:** Significantly lower than AI video. Still images with motion effects are
recognizably "slideshow" quality. Acceptable for background/ambient visuals, not for
hero content on LED walls.

**Implementation:** The codebase already has `apply_beat_sync_effects()` in
`video_models.py` with zoom pulse and brightness flash. Extend with:
- `zoompan` filter for Ken Burns (FFmpeg native)
- `hue` filter for color cycling synced to BPM
- `xfade` for crossfades between keyframes at phrase boundaries
- Use the kburns-slideshow approach for beat-synced slide timing

**Difficulty:** Low -- pure FFmpeg, no API costs.

---

## Strategy 4: Hybrid Approach (RECOMMENDED)

**Concept:** Combine strategies for optimal cost/quality ratio:

| Section Type | Method | Cost |
|-------------|--------|------|
| **Drops** | AI video (Kling v1, 10s) | $1.00/segment |
| **Breakdowns** | AI video (Wan 2.1 480p, 5s) | $0.15/segment |
| **Intros/Outros** | Image + FFmpeg Ken Burns | $0.04/segment |
| **Buildups** | Image + FFmpeg zoom pulse | $0.04/segment |

Per 4-minute track (with intra-track looping from Strategy 1):
- 2 unique drop segments (AI video): $2.00
- 1 unique breakdown segment (AI video, cheap model): $0.15
- 2 unique intro/outro segments (image + ffmpeg): $0.08
- 1 unique buildup segment (image + ffmpeg): $0.04
- Keyframe images for all: $0.24
- **Total: ~$2.50/track**

With cross-track sharing from Strategy 2 on drops:
- Drop segments shared across ~10 similar tracks
- **Effective cost: ~$1.30/track = $6,500 for 5,000 tracks**

**Difficulty:** Medium -- combines model routing (already exists) with FFmpeg fallback.

---

## Strategy 5: Self-Hosted Wan 2.1/2.2 on Rented GPUs

**Concept:** Run Wan 2.1 or 2.2 on rented A100/H100 GPUs instead of paying fal.ai
per-generation.

### Inference Speed (from benchmarks)
| GPU | 480p (5s clip) | 720p (5s clip) |
|-----|---------------|----------------|
| A100 80GB | ~170s | ~523s |
| H100 SXM | ~85s | ~284s |

### Cost Comparison: fal.ai vs Self-Hosted

**fal.ai Wan 2.1 480p:** $0.15/generation
**Self-hosted A100 ($0.78/hr spot):**
- 170s per generation = ~21 generations/hour
- Cost per generation: $0.78 / 21 = **$0.037/generation** (4x cheaper)

**fal.ai Wan 2.1 720p:** $0.25/generation
**Self-hosted A100 ($0.78/hr spot):**
- 523s per generation = ~6.9 generations/hour
- Cost per generation: $0.78 / 6.9 = **$0.113/generation** (2.2x cheaper)

**Self-hosted H100 ($1.00/hr spot):**
- 480p: 85s/gen = ~42 gens/hr = **$0.024/generation** (6x cheaper than fal.ai)
- 720p: 284s/gen = ~12.7 gens/hr = **$0.079/generation** (3x cheaper)

### Batch Processing 5,000 Tracks (Hybrid + Self-Hosted)

Using Strategy 4 hybrid with self-hosted Wan for drops + breakdowns:
- ~15,000 video segments total (3 per track after dedup)
- On H100 at 480p: 15,000 / 42 per hour = 357 GPU-hours
- Cost: 357 x $1.00 = **$357 for all video segments**
- Plus keyframe images: 5,000 x $0.24 = $1,200
- **Total: ~$1,560 for 5,000 tracks = $0.31/track**

### NAS Xeon Option
The NAS has a Xeon CPU -- no GPU. Wan 2.1 on CPU would take ~30-60 minutes per 480p
5s clip. At 15,000 segments, that is 7,500-15,000 hours. **Not viable.**

### RunPod Serverless Option
RunPod offers serverless GPU endpoints where you pay only for active inference:
- A100: ~$0.00031/second = $0.053 per 170s generation
- No idle cost, auto-scales to zero
- Best for sporadic/burst workloads

**Difficulty:** High -- requires setting up inference server, managing GPU rentals,
handling failures/retries, and checkpointing for spot instance preemption.

---

## Strategy 6: Negotiate Volume Pricing

### fal.ai Enterprise
- Contact fal.ai enterprise sales (fal.ai/enterprise)
- For 5,000+ tracks generating ~15,000+ video segments, that's significant volume
- Enterprise contracts with volume commitments typically offer 30-50% discounts
- Could bring Kling v1 from $0.10/sec to $0.05-0.07/sec

### Replicate Committed Use
- Replicate offers committed use discounts for predictable workloads
- Volume pricing starts at $500/month commitments

### Direct Model Provider APIs
- Kling direct API (api.klingai.com) may be cheaper than fal.ai markup
- MiniMax direct API similarly

**Estimated savings:** 30-50% off current API pricing.

**Difficulty:** Low -- just requires reaching out and negotiating.

---

## Strategy 7: Smart Scheduling & Progressive Quality

### Off-Peak Generation
- Some GPU cloud providers offer lower rates during off-peak hours
- Vast.ai spot pricing fluctuates -- monitor and batch during dips
- Not a massive savings but 10-20% possible

### Progressive Quality Pipeline
The codebase already has `quality_profiles.py` with draft/standard/high tiers:
1. **Draft pass** (keyframes only): $0.20/track -- review in web UI
2. **Standard pass** (720p Wan): $2/track -- for the 80% of tracks that are "good enough"
3. **High pass** (1080p Kling): $15/track -- only for hero tracks played frequently

If 10% of tracks are "hero" (500 tracks) and 90% are standard:
- 500 hero x $15 = $7,500
- 4,500 standard x $2 = $9,000
- **Total: $16,500** vs $115,000 all-high

### Smart Queue
- Track play frequency from Lexicon/Rekordbox history to prioritize generation
- Most-played tracks get high quality first
- Rarely-played tracks get draft/standard or deferred indefinitely

**Difficulty:** Low-Medium -- progressive quality already partially built.

---

## Recommended Implementation Plan

### Phase 1: Quick Wins (Week 1) -- Save 70%
1. **Intra-track segment looping** -- reuse identical sections within a song
2. **Model routing by section** -- already built in `model_router.py`, just needs tuning
3. **Use Wan 2.1 480p for non-drop sections** -- $0.15 vs $1.50 per segment
4. Target: **$7/track**

### Phase 2: Hybrid Pipeline (Week 2-3) -- Save 85%
5. **Image + FFmpeg for intros/outros/buildups** -- zero video generation cost
6. **Cross-track segment library** -- share drop visuals across similar tracks
7. Target: **$2.50/track**

### Phase 3: Self-Hosted (Week 4-6) -- Save 95%
8. **Self-hosted Wan 2.1 on RunPod/Vast.ai** -- $0.03/generation vs $0.15
9. **Batch processing pipeline** with spot instance management
10. Target: **$0.50/track**

### Phase 4: Optimization (Ongoing) -- Save 97%+
11. **Negotiate fal.ai enterprise pricing** for remaining Kling generations
12. **Play-frequency prioritization** -- only generate for tracks that get played
13. **Progressive quality** -- draft first, upgrade on demand
14. Target: **$0.30/track = $1,500 for 5,000 tracks**

---

## Cost Summary Table

| Strategy | Cost/Track | 5,000 Tracks | Savings vs Current |
|----------|-----------|-------------|-------------------|
| Current (all Kling v1.5 Pro) | $23.00 | $115,000 | -- |
| Phase 1: Loop + cheap models | $7.00 | $35,000 | 70% |
| Phase 2: Hybrid + sharing | $2.50 | $12,500 | 89% |
| Phase 3: Self-hosted Wan | $0.50 | $2,500 | 98% |
| Phase 4: Full optimization | $0.30 | $1,500 | 99% |
| Theoretical minimum (all FFmpeg) | $0.20 | $1,000 | 99.1% |

---

## Key Technical Changes Required

### pipeline.py
- Add segment deduplication within a track (hash section_label + energy_bucket)
- Add cross-track library lookup before generation
- Add FFmpeg-only fallback path for non-hero sections

### generator/video_pipeline.py
- Add FFmpeg motion generation mode (Ken Burns, zoom pulse, color cycle)
- Add self-hosted Wan endpoint support (RunPod serverless or dedicated)

### generator/model_router.py
- Add "ffmpeg" as a model option for budget sections
- Add "self-hosted-wan" provider alongside "fal" provider

### generator/cache.py
- Extend cache key to include genre/energy/mood for cross-track matching
- Add embedding-based similarity search (replace Jaccard with CLIP embeddings)

### New: generator/ffmpeg_motion.py
- Ken Burns effect generator
- Beat-synced zoom pulse generator
- Color cycling / hue rotation
- Crossfade sequencer for keyframe slideshows

### New: generator/self_hosted.py
- RunPod/Vast.ai client for self-hosted Wan inference
- Spot instance management with retry logic
- Batch queue with checkpointing

---

## Sources

- [fal.ai Pricing](https://fal.ai/pricing)
- [fal.ai Enterprise](https://fal.ai/enterprise)
- [AI Video API Cost Comparison (Medium)](https://kgabeci.medium.com/i-compared-the-cost-of-every-ai-video-api-heres-what-each-clip-actually-costs-3984ef6553e9)
- [AI API Pricing 2026 (TeamDay)](https://www.teamday.ai/blog/ai-api-pricing-comparison-2026)
- [FluxNote AI Video Pricing Guide 2026](https://fluxnote.io/blog/ai-video-generation-pricing-guide-2026)
- [H100 Rental Prices Compared (IntuitionLabs)](https://intuitionlabs.ai/articles/h100-rental-prices-cloud-comparison)
- [A100 Price Guide (JarvisLabs)](https://docs.jarvislabs.ai/blog/a100-price)
- [RunPod Pricing](https://www.runpod.io/pricing)
- [Vast.ai GPU Pricing](https://vast.ai/pricing)
- [Wan 2.1 GPU Benchmarks (InstaSD)](https://www.instasd.com/post/wan2-1-performance-testing-across-gpus)
- [Wan 2.1 on SaladCloud (Benchmark)](https://blog.salad.com/benchmarking-wan2-1/)
- [Wan2GP for GPU-Poor (GitHub)](https://github.com/deepbeepmeep/Wan2GP)
- [Deploy Wan 2.1/2.2 GPU Requirements (Spheron)](https://www.spheron.network/blog/deploy-wan-2-1-ai-video-generation-gpu-setup/)
- [Ken Burns FFmpeg (Bannerbear)](https://www.bannerbear.com/blog/how-to-do-a-ken-burns-style-effect-with-ffmpeg/)
- [kburns-slideshow (GitHub)](https://github.com/Trekky12/kburns-slideshow)
- [AI GPU Rental Market Trends March 2026](https://www.thundercompute.com/blog/ai-gpu-rental-market-trends)
