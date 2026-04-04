# Changelog

## [2.0.0] - 2026-04-03

### Added
- **V2 Loop-Bank Architecture**: Generate 5-10 short loops per song instead of 24+ linear segments. 58% cost reduction.
- **Beat-Sync Post-Processing**: ffmpeg brightness flash on every beat, zoom pulse on every bar, synced to BPM.
- **Rich Metadata**: Phrase timeline, energy curves, mood gauges, stem analysis, cost breakdown per track.
- **Web UI**: 17-page React dashboard running in Docker on NAS.
  - Dashboard with system status, quick stats, pause/resume
  - Library with 5,000+ track browsing, sorting, filtering by genre
  - Genre browser with 179 genres and visual completion stats
  - Generation queue with real-time WebSocket progress
  - Budget dashboard with cost tracking, projections, credit status
  - Brand editor with form-based visual identity management
  - 14 video model comparison with tier grouping
  - Resolume settings for .avc composition configuration
  - OSC control, setlists, presets, timeline editor, comparison viewer
  - Setup wizard for first-run configuration
  - Auto-update system for Docker deployments
- **Cost Protection**: $30 per-song hard cap, Veo 2 blocked for full songs, auto-downgrade to cheaper models, credit exhaustion warnings.
- **Phrase-Aligned Segments**: Visual changes hit exactly on drops, breakdowns, and buildups.
- **45 Genre Modifiers**: Unique visual vocabularies for bass music, house, techno, trance, breaks, hard dance, downtempo, trap, synthwave, experimental.
- **Stem Separation**: Demucs-powered drum/bass/synth/vocal isolation with 5,000+ sonic events per track.
- **Mood Analysis**: Essentia-powered happy/sad/aggressive/relaxed/party detection with Russell's circumplex mapping.
- **Lyrics/Title Analysis**: GPT interpretation of track titles and lyrics for visual theming.
- **Lexicon DJ Integration**: Pull DJ-verified BPM, key, genre, energy from Lexicon's REST API.
- **Denon StagelinQ**: Auto-trigger visuals when tracks load on SC6000 via timecode sync.
- **DXV Encoding**: GPU-decoded Resolume-native codec output.
- **NAS File Management**: Organized show structure with auto .avc rebuild.

### Models Supported
- **Video**: Kling v1/v1.5 Pro/v2, MiniMax, MiniMax Live, Google Veo 2/3, Wan 2.1 (480p/720p/1080p), Runway Gen-3, Luma Ray 2, Pika 2, CogVideoX
- **Image**: DALL-E 3, Flux Schnell, Google Imagen 3/Fast

## [0.1.0] - 2026-03-27

### Added
- Initial implementation: music analysis + AI visual generation
- BPM detection, beat tracking, phrase segmentation
- DALL-E 3 keyframe generation with beat-synced PIL animation
- 10 visual style presets
- Resolume Arena .avc composition export
- CLI with analyze, generate, bulk, watch commands
