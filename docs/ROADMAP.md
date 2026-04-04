# Resolume Sync Visuals -- Roadmap

Organized by priority tier. Each tier builds on the previous one, turning this from a solid generation pipeline into a complete VJ visual platform.

---

## Tier 1: Core Quality (Immediate Impact)

These features directly improve the quality of every generated video with minimal architectural changes.

| # | Feature | Category |
|---|---------|----------|
| [#35](https://github.com/rancur/resolume-sync-visuals/issues/35) | Motion intensity mapping from audio energy envelope | visual-quality, music-analysis |
| [#36](https://github.com/rancur/resolume-sync-visuals/issues/36) | Color palette extraction from album art | visual-quality |
| [#46](https://github.com/rancur/resolume-sync-visuals/issues/46) | Custom prompt injection per track | ux |
| [#49](https://github.com/rancur/resolume-sync-visuals/issues/49) | Genre-specific visual vocabularies | visual-quality, music-analysis |
| [#38](https://github.com/rancur/resolume-sync-visuals/issues/38) | Drop prediction and buildup-aware visual anticipation | music-analysis |
| [#56](https://github.com/rancur/resolume-sync-visuals/issues/56) | Backup clip generation (fallback visuals) | resolume |

**Why first:** These plug into the existing pipeline with focused changes to the analyzer and prompt engine. Every video generated after these land will be noticeably better. Motion mapping and drop prediction are the highest-leverage audio-visual sync improvements. Backup clips solve the "DJ plays an unknown track" problem that every VJ faces.

---

## Tier 2: Pipeline Power (Scale and Efficiency)

Make generation faster, cheaper, and more reliable before scaling up the library.

| # | Feature | Category |
|---|---------|----------|
| [#50](https://github.com/rancur/resolume-sync-visuals/issues/50) | Progressive rendering: low-res preview then high-res final | performance |
| [#45](https://github.com/rancur/resolume-sync-visuals/issues/45) | Batch generation queue with priority and scheduling | ux, operations |
| [#52](https://github.com/rancur/resolume-sync-visuals/issues/52) | Automatic quality checks on generated videos | operations |
| [#58](https://github.com/rancur/resolume-sync-visuals/issues/58) | Smart keyframe caching to reduce regeneration cost | performance |
| [#51](https://github.com/rancur/resolume-sync-visuals/issues/51) | Parallel generation across multiple API keys | performance |
| [#61](https://github.com/rancur/resolume-sync-visuals/issues/61) | Multi-model pipeline: different AI models per section | visual-quality, performance |
| [#54](https://github.com/rancur/resolume-sync-visuals/issues/54) | Version tracking and rollback for generated videos | operations |

**Why second:** Progressive rendering alone cuts wasted spend by 70%+ (reject bad results at draft quality). The priority queue and scheduling enable overnight batch runs. Quality checks catch duds before they hit the stage. These are the foundation for processing an entire library without babysitting.

---

## Tier 3: Resolume Deep Integration

Unlock Resolume capabilities beyond flat video playback.

| # | Feature | Category |
|---|---------|----------|
| [#43](https://github.com/rancur/resolume-sync-visuals/issues/43) | Effect automation tied to song sections in .avc | resolume |
| [#41](https://github.com/rancur/resolume-sync-visuals/issues/41) | Multi-layer compositions (background + foreground + overlay) | resolume |
| [#48](https://github.com/rancur/resolume-sync-visuals/issues/48) | Set-list aware compositions with transition planning | resolume |
| [#42](https://github.com/rancur/resolume-sync-visuals/issues/42) | Live OSC parameter control for real-time visual adjustment | resolume |
| [#31](https://github.com/rancur/resolume-sync-visuals/issues/31) | Auto-rebuild show when new tracks are generated | resolume |
| [#29](https://github.com/rancur/resolume-sync-visuals/issues/29) | Research and validate .avc format for Resolume 7+ | resolume |

**Why third:** These transform the output from "video files that play in Resolume" to "an intelligent Resolume show that reacts and transitions." Effect automation and multi-layer are the biggest differentiators vs. just playing a video. Set-list awareness makes this a show-planning tool, not just a clip generator. OSC adds live reactivity on top of pre-rendered content.

---

## Tier 4: Visual Intelligence

Advanced visual analysis and creative features that push quality to the next level.

| # | Feature | Category |
|---|---------|----------|
| [#37](https://github.com/rancur/resolume-sync-visuals/issues/37) | A/B visual generation with quality scoring | visual-quality |
| [#34](https://github.com/rancur/resolume-sync-visuals/issues/34) | Style transfer from reference videos and images | visual-quality |
| [#64](https://github.com/rancur/resolume-sync-visuals/issues/64) | Visual consistency scoring across a full set | visual-quality, operations |
| [#39](https://github.com/rancur/resolume-sync-visuals/issues/39) | Key change detection triggers visual color shifts | music-analysis, visual-quality |
| [#62](https://github.com/rancur/resolume-sync-visuals/issues/62) | Seasonal and venue-specific theme layers | visual-quality |
| [#63](https://github.com/rancur/resolume-sync-visuals/issues/63) | Sample and loop detection for visual repetition patterns | music-analysis |

**Why fourth:** These are the "wow" features that separate good from great. A/B testing with scoring makes generation self-improving. Style transfer lets users achieve any look. Consistency scoring ensures the whole set feels cohesive. These require the quality checks and version tracking from Tier 2 to be most effective.

---

## Tier 5: User Experience Polish

Make the platform accessible and enjoyable to use.

| # | Feature | Category |
|---|---------|----------|
| [#44](https://github.com/rancur/resolume-sync-visuals/issues/44) | Visual timeline editor with drag-to-adjust section boundaries | ux |
| [#60](https://github.com/rancur/resolume-sync-visuals/issues/60) | Before/after comparison viewer for visual iterations | ux |
| [#47](https://github.com/rancur/resolume-sync-visuals/issues/47) | Favorite styles and reusable visual presets | ux |
| [#40](https://github.com/rancur/resolume-sync-visuals/issues/40) | Vocal isolation for lyric display overlays | music-analysis, visual-quality |
| [#59](https://github.com/rancur/resolume-sync-visuals/issues/59) | Mobile-friendly web UI for remote monitoring | ux |

**Why fifth:** The timeline editor is the most complex UI component and needs the underlying pipeline to be stable first. Comparison viewer requires version tracking (Tier 2). Presets need enough generation history to be meaningful. Lyric overlays are a niche feature that adds significant complexity. Mobile UI is polish on top of a working web UI.

---

## Tier 6: Infrastructure and Scale

Long-term infrastructure for running this as a production service.

| # | Feature | Category |
|---|---------|----------|
| [#53](https://github.com/rancur/resolume-sync-visuals/issues/53) | Discord and email notifications on generation completion | operations |
| [#55](https://github.com/rancur/resolume-sync-visuals/issues/55) | Disk space monitoring with smart cleanup | operations |
| [#57](https://github.com/rancur/resolume-sync-visuals/issues/57) | Audio fingerprinting for automatic track identification | music-analysis |
| [#65](https://github.com/rancur/resolume-sync-visuals/issues/65) | CDN-backed preview serving for fast remote access | performance |
| [#27](https://github.com/rancur/resolume-sync-visuals/issues/27) | Add CI/CD pipeline (GitHub Actions) | operations |

**Why last:** These are operational conveniences that matter at scale but aren't blocking creative output. Notifications are nice-to-have when generation already works reliably. Audio fingerprinting solves an edge case. CDN is only needed when serving previews remotely at volume.

---

## Feature Dependency Graph

```
Tier 1 (Core Quality)
  |
  v
Tier 2 (Pipeline Power)
  |-- Progressive rendering --> A/B testing (Tier 4)
  |-- Version tracking ------> Comparison viewer (Tier 5)
  |-- Quality checks --------> Consistency scoring (Tier 4)
  |-- Batch queue -----------> Notifications (Tier 6)
  |
  v
Tier 3 (Resolume Deep)          Tier 4 (Visual Intelligence)
  |-- Multi-layer ---|            |-- Style transfer
  |-- Effect auto ---|            |-- Seasonal themes
  |-- Set-list ------|            |
  |                  v            v
  v              Tier 5 (UX Polish)
Tier 6             |-- Timeline editor
(Infrastructure)   |-- Comparison viewer
                   |-- Presets
```

---

## Quick Wins (Can Be Done Anytime)

These are small-scope features that can be picked up independently regardless of current tier:

- **#36** Color palette extraction from album art (few hours, high visual impact)
- **#46** Custom prompt injection per track (CLI flag + prompt concatenation)
- **#56** Backup clip generation (standalone generation job)
- **#53** Discord notifications (webhook POST, no dependencies)
- **#55** Disk space monitoring (SSH df + threshold check)

---

## Tracking

Total open feature issues: 32
- Visual Quality: 10
- Music Analysis: 7
- Resolume Integration: 7
- User Experience: 7
- Operations: 7
- Performance: 6

*Last updated: 2026-03-27*
