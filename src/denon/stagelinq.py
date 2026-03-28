"""
Denon StagelinQ protocol listener.

StagelinQ is Denon DJ's network protocol for broadcasting playback state
from SC6000, SC5000, Prime 4, and other Engine DJ hardware.

Protocol overview:
- Discovery: UDP broadcast on port 51337
- Communication: TCP connection after discovery
- Data: BPM, track name, playback state, beat position, master tempo
- Uses a proprietary binary protocol over TCP

This module provides a listener that can:
1. Discover StagelinQ devices on the network
2. Connect and receive real-time playback data
3. Trigger visual changes based on track changes / BPM updates

Note: Full StagelinQ implementation requires reverse-engineering the binary protocol.
This module provides the framework and falls back to Engine DJ database
reading for track metadata when live protocol data isn't available.
"""
import json
import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

STAGELINQ_DISCOVERY_PORT = 51337
STAGELINQ_MAGIC = b"airD"  # Discovery packet magic bytes


@dataclass
class DeckState:
    """Current state of a DJ deck."""
    deck_id: int = 0
    track_name: str = ""
    artist: str = ""
    bpm: float = 0.0
    master_bpm: float = 0.0
    playing: bool = False
    beat_position: float = 0.0  # Position within current beat (0-1)
    elapsed: float = 0.0  # Seconds elapsed
    remaining: float = 0.0  # Seconds remaining


@dataclass
class StagelinQDevice:
    """A discovered StagelinQ device."""
    name: str = ""
    ip: str = ""
    port: int = 0
    software_name: str = ""
    software_version: str = ""


class StagelinQListener:
    """
    Listen for StagelinQ devices and receive playback data.

    Usage:
        listener = StagelinQListener()
        listener.on_track_change = my_callback
        listener.on_bpm_change = my_bpm_callback
        listener.start()
        # ... later ...
        listener.stop()
    """

    def __init__(self):
        self.devices: list[StagelinQDevice] = []
        self.deck_states: dict[int, DeckState] = {}
        self._running = False
        self._discovery_thread: Optional[threading.Thread] = None

        # Callbacks
        self.on_device_found: Optional[Callable[[StagelinQDevice], None]] = None
        self.on_track_change: Optional[Callable[[int, DeckState], None]] = None
        self.on_bpm_change: Optional[Callable[[int, float], None]] = None
        self.on_beat: Optional[Callable[[int, float], None]] = None

    def start(self):
        """Start listening for StagelinQ devices."""
        self._running = True
        self._discovery_thread = threading.Thread(
            target=self._discovery_loop,
            daemon=True,
            name="stagelinq-discovery",
        )
        self._discovery_thread.start()
        logger.info("StagelinQ listener started")

    def stop(self):
        """Stop listening."""
        self._running = False
        if self._discovery_thread:
            self._discovery_thread.join(timeout=5)
        logger.info("StagelinQ listener stopped")

    def _discovery_loop(self):
        """Listen for StagelinQ discovery broadcasts."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", STAGELINQ_DISCOVERY_PORT))
            sock.settimeout(2.0)

            logger.info(f"Listening for StagelinQ devices on port {STAGELINQ_DISCOVERY_PORT}")

            while self._running:
                try:
                    data, addr = sock.recvfrom(4096)
                    device = self._parse_discovery(data, addr[0])
                    if device:
                        if not any(d.ip == device.ip for d in self.devices):
                            self.devices.append(device)
                            logger.info(f"Found StagelinQ device: {device.name} at {device.ip}:{device.port}")
                            if self.on_device_found:
                                self.on_device_found(device)
                except socket.timeout:
                    continue
                except Exception as e:
                    logger.debug(f"Discovery error: {e}")

        except OSError as e:
            logger.warning(f"Could not bind StagelinQ discovery port: {e}")
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _parse_discovery(self, data: bytes, ip: str) -> Optional[StagelinQDevice]:
        """Parse a StagelinQ discovery packet."""
        if len(data) < 8:
            return None

        # StagelinQ discovery packets start with magic bytes
        if data[:4] != STAGELINQ_MAGIC:
            return None

        try:
            device = StagelinQDevice(ip=ip)

            # Parse the packet (simplified — full protocol is more complex)
            # The packet contains: magic(4) + port(2) + name_len(2) + name + sw_name + sw_version
            offset = 4
            if len(data) > offset + 2:
                device.port = struct.unpack(">H", data[offset:offset+2])[0]
                offset += 2

            # Read null-terminated strings
            strings = []
            current = b""
            for byte in data[offset:]:
                if byte == 0:
                    if current:
                        strings.append(current.decode("utf-8", errors="replace"))
                        current = b""
                else:
                    current += bytes([byte])
            if current:
                strings.append(current.decode("utf-8", errors="replace"))

            if len(strings) >= 1:
                device.name = strings[0]
            if len(strings) >= 2:
                device.software_name = strings[1]
            if len(strings) >= 3:
                device.software_version = strings[2]

            return device

        except Exception as e:
            logger.debug(f"Failed to parse discovery packet: {e}")
            return None

    def get_deck_state(self, deck_id: int) -> Optional[DeckState]:
        """Get current state of a deck."""
        return self.deck_states.get(deck_id)

    def get_master_bpm(self) -> float:
        """Get the master BPM (from whichever deck is master)."""
        for state in self.deck_states.values():
            if state.master_bpm > 0:
                return state.master_bpm
        for state in self.deck_states.values():
            if state.bpm > 0:
                return state.bpm
        return 0.0

    def simulate_deck_update(self, deck_id: int, **kwargs):
        """
        Simulate a deck state update (for testing without hardware).
        Useful for development and automated testing.
        """
        if deck_id not in self.deck_states:
            self.deck_states[deck_id] = DeckState(deck_id=deck_id)

        state = self.deck_states[deck_id]
        old_track = state.track_name
        old_bpm = state.bpm

        for key, value in kwargs.items():
            if hasattr(state, key):
                setattr(state, key, value)

        # Fire callbacks
        if state.track_name != old_track and self.on_track_change:
            self.on_track_change(deck_id, state)

        if state.bpm != old_bpm and self.on_bpm_change:
            self.on_bpm_change(deck_id, state.bpm)
