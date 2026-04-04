# Web UI Architecture

See the full plan in the git history. Key decisions:
- Backend: FastAPI with asyncio job queue
- Frontend: React + Vite + Tailwind CSS
- Docker: multi-stage build (Node frontend → Python backend)
- Real-time: WebSocket for generation progress
- Storage: SQLite (extending existing tracking DBs)
- NAS: SSH tunnel from container
- Auto-update: Watchtower for container images
