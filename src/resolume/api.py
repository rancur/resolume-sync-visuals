"""
Resolume Arena REST API client.

Communicates with a running Resolume Arena instance to:
- Load video files into clips
- Set clip transport modes (Timeline, BPMSync, Denon)
- Configure clip targets (Denon Player Determined)
- Add/remove layers and columns
- Query composition state

Resolume Arena exposes a REST API on port 8080 by default.
Enable it in Preferences > Webserver.

Reference: https://resolume.com/docs/restapi/
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
REQUEST_TIMEOUT = 10.0


class ResolumeAPI:
    """Client for Resolume Arena's REST API."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = REQUEST_TIMEOUT,
    ):
        self.base_url = f"http://{host}:{port}/api/v1"
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ------------------------------------------------------------------
    # Health / Info
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Check if Resolume is reachable."""
        try:
            r = self._client.get(f"{self.base_url}/composition")
            return r.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    def get_composition(self) -> dict:
        """Get the full composition state."""
        r = self._client.get(f"{self.base_url}/composition")
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Composition structure
    # ------------------------------------------------------------------

    def get_layers(self) -> list[dict]:
        """Get all layers in the composition."""
        comp = self.get_composition()
        return comp.get("layers", [])

    def get_columns(self) -> list[dict]:
        """Get all columns in the composition."""
        comp = self.get_composition()
        return comp.get("columns", [])

    def add_layer(self) -> dict:
        """Add a new layer to the composition."""
        r = self._client.post(f"{self.base_url}/composition/layers")
        r.raise_for_status()
        return r.json() if r.text else {}

    def add_column(self) -> dict:
        """Add a new column to the composition."""
        r = self._client.post(f"{self.base_url}/composition/columns")
        r.raise_for_status()
        return r.json() if r.text else {}

    def clear_layer(self, layer: int):
        """Clear all clips from a layer (1-indexed)."""
        r = self._client.post(
            f"{self.base_url}/composition/layers/{layer}/clear"
        )
        r.raise_for_status()

    def clear_column(self, column: int):
        """Clear a column (1-indexed)."""
        r = self._client.post(
            f"{self.base_url}/composition/columns/{column}/clear"
        )
        r.raise_for_status()

    def set_layer_name(self, layer: int, name: str):
        """Set the name of a layer (1-indexed)."""
        r = self._client.put(
            f"{self.base_url}/composition/layers/{layer}",
            json={"name": {"value": name}},
        )
        r.raise_for_status()

    def set_column_name(self, column: int, name: str):
        """Set the name of a column (1-indexed)."""
        r = self._client.put(
            f"{self.base_url}/composition/columns/{column}",
            json={"name": {"value": name}},
        )
        r.raise_for_status()

    # ------------------------------------------------------------------
    # Clip operations
    # ------------------------------------------------------------------

    def load_clip(self, layer: int, column: int, file_path: str):
        """Load a video file into a clip slot.

        Args:
            layer: Layer index (1-indexed)
            column: Column index (1-indexed)
            file_path: Absolute path to the video file.
                       Will be converted to file:/// URI.
        """
        # Resolume expects file:/// URI with forward slashes
        clean_path = file_path.replace("\\", "/")
        if not clean_path.startswith("/"):
            clean_path = "/" + clean_path
        file_uri = f"file://{clean_path}"

        r = self._client.post(
            f"{self.base_url}/composition/layers/{layer}/clips/{column}/open",
            content=file_uri,
            headers={"Content-Type": "text/plain"},
        )
        r.raise_for_status()
        logger.debug(f"Loaded clip: layer={layer} col={column} path={file_path}")

    def get_clip(self, layer: int, column: int) -> dict:
        """Get clip state at a position."""
        r = self._client.get(
            f"{self.base_url}/composition/layers/{layer}/clips/{column}"
        )
        r.raise_for_status()
        return r.json()

    def set_clip_transport_type(self, layer: int, column: int, transport_type: str):
        """Set the transport type for a clip.

        Args:
            layer: Layer index (1-indexed)
            column: Column index (1-indexed)
            transport_type: One of "Timeline", "BPMSync", "Denon", "SMPTE"
        """
        r = self._client.put(
            f"{self.base_url}/composition/layers/{layer}/clips/{column}",
            json={"transporttype": {"value": transport_type}},
        )
        r.raise_for_status()
        logger.debug(f"Set transport: layer={layer} col={column} type={transport_type}")

    def set_clip_target(self, layer: int, column: int, target: str):
        """Set the clip target (for Denon integration).

        Args:
            layer: Layer index (1-indexed)
            column: Column index (1-indexed)
            target: e.g. "Denon Player Determined", "Any", "Player 1", etc.
        """
        r = self._client.put(
            f"{self.base_url}/composition/layers/{layer}/clips/{column}",
            json={"target": {"value": target}},
        )
        r.raise_for_status()
        logger.debug(f"Set target: layer={layer} col={column} target={target}")

    def set_clip_name(self, layer: int, column: int, name: str):
        """Set the name/label of a clip."""
        r = self._client.put(
            f"{self.base_url}/composition/layers/{layer}/clips/{column}",
            json={"name": {"value": name}},
        )
        r.raise_for_status()

    def connect_clip(self, layer: int, column: int):
        """Trigger/connect a clip (start playing)."""
        r = self._client.post(
            f"{self.base_url}/composition/layers/{layer}/clips/{column}/connect",
            json=1,
        )
        r.raise_for_status()

    def disconnect_clip(self, layer: int, column: int):
        """Disconnect a clip (stop playing)."""
        r = self._client.post(
            f"{self.base_url}/composition/layers/{layer}/clips/{column}/connect",
            json=0,
        )
        r.raise_for_status()

    # ------------------------------------------------------------------
    # Tempo
    # ------------------------------------------------------------------

    def set_tempo(self, bpm: float):
        """Set the master tempo."""
        r = self._client.put(
            f"{self.base_url}/composition/tempocontroller/tempo",
            json={"value": bpm},
        )
        r.raise_for_status()

    def get_tempo(self) -> Optional[float]:
        """Get the current master tempo."""
        r = self._client.get(
            f"{self.base_url}/composition/tempocontroller/tempo"
        )
        r.raise_for_status()
        data = r.json()
        return data.get("value")

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def get_sources(self) -> dict:
        """List all available sources (video generators, etc.)."""
        r = self._client.get(f"{self.base_url}/sources")
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # High-level: Build Denon show
    # ------------------------------------------------------------------

    def build_denon_show(
        self,
        tracks: list[dict],
        layer: int = 1,
        start_column: int = 1,
        set_target: bool = True,
        delay_between: float = 0.5,
    ) -> int:
        """Load tracks into Resolume as Denon-transport clips.

        This is the production method for setting up the show.
        It loads each track's video into consecutive columns on a single layer,
        sets each to Denon transport mode, and sets the clip target to
        "Denon Player Determined".

        Args:
            tracks: List of track dicts with:
                - title: str (ID3 title, used as clip name)
                - video_path: str (absolute path to .mov as Resolume sees it)
            layer: Which layer to load clips into (1-indexed, default 1)
            start_column: Starting column (1-indexed, default 1)
            set_target: Whether to set clip target to Denon Player Determined
            delay_between: Seconds to wait between clip loads (avoid overloading)

        Returns:
            Number of clips successfully loaded.
        """
        loaded = 0
        for i, track in enumerate(tracks):
            col = start_column + i
            title = track.get("title", f"Track {col}")
            video_path = track.get("video_path", track.get("local_vj_path", ""))

            if not video_path:
                logger.warning(f"No video path for '{title}', skipping")
                continue

            try:
                # Ensure column exists (add if needed)
                # Resolume auto-extends, but we ensure enough columns
                self.load_clip(layer, col, video_path)

                # Small delay for Resolume to process the file load
                if delay_between > 0:
                    time.sleep(delay_between)

                # Set transport to Denon
                self.set_clip_transport_type(layer, col, "Denon")

                # Set clip target for auto-matching
                if set_target:
                    self.set_clip_target(layer, col, "Denon Player Determined")

                # Set clip name to match ID3 title
                self.set_clip_name(layer, col, title)

                loaded += 1
                logger.info(f"[{loaded}] Loaded: {title} -> layer={layer} col={col}")

            except Exception as e:
                logger.error(f"Failed to load '{title}': {e}")

        logger.info(f"Denon show: {loaded}/{len(tracks)} clips loaded")
        return loaded
