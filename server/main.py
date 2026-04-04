"""
FastAPI application for the RSV (Resolume Sync Visuals) web UI.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .services.job_queue import start_worker, stop_worker
from .websocket import ws_manager

from .routers.tracks import router as tracks_router, playlist_router
from .routers.generation import router as generation_router
from .routers.budget import router as budget_router
from .routers.brands import router as brands_router
from .routers.models_router import router as models_router
from .routers.settings import router as settings_router
from .routers.logs import router as logs_router
from .routers.preview import router as preview_router
from .routers.genres import router as genres_router
from .routers.setup import router as setup_router
from .routers.system import router as system_router
from .routers.dashboard import router as dashboard_router
from .routers.resolume_settings import router as resolume_settings_router
from .routers.backups import router as backups_router
from .routers.presets import router as presets_router
from .routers.pipeline_config import router as pipeline_config_router
from .routers.osc import router as osc_router
from .routers.setlists import router as setlists_router
from .routers.videos import router as videos_router
from .routers.vocals import router as vocals_router
from src import __version__

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("RSV server starting up")
    init_db()
    await start_worker()
    yield
    # Shutdown
    await stop_worker()
    logger.info("RSV server shut down")


app = FastAPI(
    title="Resolume Sync Visuals",
    description="AI video generation pipeline for DJ sets",
    version=__version__,
    lifespan=lifespan,
)

# CORS — allow all origins for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(tracks_router)
app.include_router(playlist_router)
app.include_router(generation_router)
app.include_router(budget_router)
app.include_router(brands_router)
app.include_router(models_router)
app.include_router(settings_router)
app.include_router(logs_router)
app.include_router(preview_router)
app.include_router(genres_router)
app.include_router(setup_router)
app.include_router(system_router)
app.include_router(dashboard_router)
app.include_router(resolume_settings_router)
app.include_router(backups_router)
app.include_router(presets_router)
app.include_router(osc_router)
app.include_router(pipeline_config_router)
app.include_router(setlists_router)
app.include_router(videos_router)
app.include_router(vocals_router)


# Health check
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "rsv",
        "websocket_clients": ws_manager.client_count,
    }


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            # Keep connection alive; clients send pings
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


# Static file serving for built React app (must be last)
# Check multiple possible paths
_STATIC_DIR = None
for _candidate in [
    Path("/app/static"),
    Path("/app/web/dist"),
    Path(__file__).parent.parent / "web" / "dist",
]:
    if _candidate.exists() and (_candidate / "index.html").exists():
        _STATIC_DIR = _candidate
        break

if _STATIC_DIR:
    from fastapi.responses import FileResponse

    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(_STATIC_DIR / "assets")), name="assets")

    # SPA catch-all: serve index.html for any non-API route
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # If the file exists in dist, serve it (favicon, icons, etc.)
        file_path = _STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        # Otherwise serve index.html for client-side routing
        return FileResponse(str(_STATIC_DIR / "index.html"))
