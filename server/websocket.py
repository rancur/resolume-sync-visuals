"""
WebSocket connection manager for real-time job updates.
"""
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts updates."""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)
        logger.info(f"WebSocket connected ({len(self._connections)} total)")

    def disconnect(self, ws: WebSocket):
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info(f"WebSocket disconnected ({len(self._connections)} total)")

    async def broadcast(self, message: dict[str, Any]):
        """Send a JSON message to all connected clients."""
        data = json.dumps(message)
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(data)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    async def send_job_update(
        self,
        job_id: str,
        status: str,
        progress: float = 0.0,
        message: str = "",
        **extra,
    ):
        """Convenience: broadcast a job progress event."""
        await self.broadcast({
            "type": "job_update",
            "job_id": job_id,
            "status": status,
            "progress": progress,
            "message": message,
            **extra,
        })

    @property
    def client_count(self) -> int:
        return len(self._connections)


# Singleton
ws_manager = ConnectionManager()
