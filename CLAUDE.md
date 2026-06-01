# CLAUDE.md -- resolume-sync-visuals

## What This Is
Full-length AI video generation for DJ sets. Analyzes audio tracks (BPM, key, energy, phrases), generates style-matched visuals via AI models (Replicate, fal, OpenAI DALL-E), and outputs Resolume Arena-ready video clips. Supports Lexicon DJ library scanning and Denon StagelinQ live integration.

## Quick Start
```bash
# Activate the venv (required -- system Python won't have deps)
source .venv/bin/activate

# Run tests
python3 -m pytest tests/ -v

# CLI entry point
rsv --help
```

## Project Structure
- `src/` -- Main package
  - `analyzer/` -- Audio analysis (BPM, key, energy, stems via demucs)
  - `generator/` -- AI video generation (model routing, pipelines, prompt building)
  - `composer/` -- Video composition and montage
  - `cli.py` -- Click-based CLI (`rsv` command)
  - `watcher.py` -- Watchdog-based folder watcher for auto-processing
  - `scanner.py` -- Lexicon DJ library scanner
  - `validation.py` -- Audio file validation
  - `cost_guard.py` -- Per-song cost caps for AI model usage
- `server/` -- Web server / API
- `config/` -- Style presets and configuration YAML files
- `tests/` -- pytest test suite (1191 tests)
- `scripts/` -- Utility scripts
- `web/` -- Web frontend assets

## Testing
```bash
source .venv/bin/activate
python3 -m pytest tests/ -v           # All tests
python3 -m pytest tests/test_foo.py   # Single file
```

The venv must be active. The project depends on librosa, soundfile, opencv-python, httpx, and other native packages that are only installed in `.venv/`.

## Key Details
- Python >=3.9, venv uses 3.13
- Version: 2.0.0 (pyproject.toml, git tag v2.0.0)
- Entry point: `rsv` CLI (src.cli:main)
- Optional `[mood]` extra for essentia-tensorflow
- Dev deps: `pip install -e ".[dev]"`
