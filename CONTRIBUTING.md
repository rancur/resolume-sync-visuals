# Contributing to Resolume Sync Visuals

Thanks for your interest in contributing! This project generates AI-powered visuals for DJs using Resolume Arena.

## Getting Started

1. Fork the repo
2. Clone your fork: `git clone https://github.com/YOUR-USERNAME/resolume-sync-visuals.git`
3. Create a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`
4. Install dependencies: `pip install -e ".[dev]"`
5. Run tests: `python -m pytest tests/ --ignore=tests/test_e2e.py`

## Development

- **Backend**: Python 3.9+, FastAPI server in `server/`
- **Frontend**: React + Vite + Tailwind in `web/`
- **Core pipeline**: `src/` — analyzers, generators, encoders
- **Tests**: `tests/` — 1,100+ tests

### Running locally

```bash
# Backend
source .venv/bin/activate
uvicorn server.main:app --port 8000 --reload

# Frontend (dev mode)
cd web && npm run dev
```

### Running with Docker

```bash
docker compose up -d
```

## Pull Requests

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make your changes
3. Run tests: `python -m pytest tests/ --ignore=tests/test_e2e.py`
4. Build frontend: `cd web && npm run build`
5. Commit with a clear message
6. Open a PR against `main`

## Code Style

- Python: follow existing patterns, type hints appreciated
- TypeScript: follow existing patterns
- Tests for new features are required

## Reporting Issues

Use GitHub Issues with the provided templates. Include:
- Steps to reproduce
- Expected vs actual behavior
- System info (OS, Python version, Docker version)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
