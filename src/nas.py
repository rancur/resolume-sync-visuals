"""
NAS file management for vj-content.

Manages the folder structure on the Synology NAS at /volume1/vj-content/:

    /volume1/vj-content/
    ├── shows/                                 ← Resolume compositions
    │   ├── My Show.avc
    │   └── House Set.avc
    ├── Nan Slapper (Original Mix)/            ← One folder per song
    │   ├── Nan Slapper (Original Mix).mov     ← DXV video for Resolume
    │   ├── Nan Slapper (Original Mix).mp4     ← H.264 preview with audio
    │   ├── metadata.json                      ← Track analysis + generation metadata
    │   ├── keyframes/                         ← Generated keyframe images
    │   │   ├── segment_000_intro.png
    │   │   └── ...
    │   └── stems/                             ← Separated stem WAVs (optional)
    │       ├── drums.wav
    │       ├── bass.wav
    │       ├── other.wav
    │       └── vocals.wav
    └── .rsv/                                  ← System metadata
        ├── registry.json                      ← Which tracks have been generated
        └── generation_log.json                ← Cost tracking, errors

Connection: SSH on port 7844, no SCP — uses SSH cat for file transfer.
Resolume on the M4 Mac Mini mounts the NAS share, so paths need translation:
    NAS:      /volume1/vj-content/Track Name/Track Name.mov
    Resolume: /Volumes/vj-content/Track Name/Track Name.mov
"""
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Defaults (matching existing lexicon.py constants)
DEFAULT_NAS_HOST = os.environ.get("NAS_HOST", "localhost")
DEFAULT_NAS_SSH_PORT = int(os.environ.get("NAS_SSH_PORT", "7844"))
DEFAULT_NAS_USER = os.environ.get("NAS_USER", "admin")
DEFAULT_NAS_SSH_KEY = Path(os.environ.get("NAS_SSH_KEY", str(Path.home() / ".ssh" / "id_ed25519")))
DEFAULT_BASE_PATH = "/volume1/vj-content"
DEFAULT_RESOLUME_MOUNT = "/Volumes/vj-content"


class NASManager:
    """Manage the vj-content folder structure on the NAS.

    Supports two modes:
    1. SSH mode (default): Push/pull files via SSH (for remote access).
    2. Direct mode: When running inside a Docker container on the NAS
       with the vj-content volume mounted, use direct filesystem I/O.
       Set ``direct_path`` to the container-local mount point (e.g. "/vj-content").
    """

    def __init__(
        self,
        nas_host: str = DEFAULT_NAS_HOST,
        nas_port: int = DEFAULT_NAS_SSH_PORT,
        nas_user: str = DEFAULT_NAS_USER,
        ssh_key: Path = DEFAULT_NAS_SSH_KEY,
        base_path: str = DEFAULT_BASE_PATH,
        resolume_mount: str = DEFAULT_RESOLUME_MOUNT,
        direct_path: str = "",
    ):
        self.nas_host = nas_host
        self.nas_port = nas_port
        self.nas_user = nas_user
        self.ssh_key = ssh_key
        self.base_path = base_path.rstrip("/")
        self.resolume_mount = resolume_mount.rstrip("/")
        # When set, maps base_path prefix to this local mount for direct I/O.
        # e.g. direct_path="/vj-content" maps /volume1/vj-content/... to /vj-content/...
        self.direct_path = direct_path.rstrip("/") if direct_path else ""

    def _to_local(self, nas_path: str) -> str:
        """Convert a NAS path to the container-local path (direct mode only)."""
        if not self.direct_path:
            return nas_path
        # Replace /volume1/vj-content prefix with direct mount
        # base_path might already be show-specific, but the NAS absolute prefix
        # is always /volume1/vj-content
        for prefix in ["/volume1/vj-content", self.base_path]:
            if nas_path.startswith(prefix):
                return self.direct_path + nas_path[len(prefix):]
        return nas_path

    # ------------------------------------------------------------------
    # SSH transport
    # ------------------------------------------------------------------

    def _ssh_cmd(
        self, remote_cmd: str, timeout: float = 30.0
    ) -> subprocess.CompletedProcess:
        """Run a command on the NAS via SSH (or locally in direct mode)."""
        if self.direct_path:
            # Direct mode: translate NAS paths to container-local paths
            # Replace /volume1/vj-content with the direct mount
            mapped_cmd = remote_cmd.replace("/volume1/vj-content", self.direct_path)
            return subprocess.run(
                ["sh", "-c", mapped_cmd],
                capture_output=True, timeout=timeout,
            )
        ssh_args = [
            "ssh",
            "-p", str(self.nas_port),
            "-i", str(self.ssh_key),
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{self.nas_user}@{self.nas_host}",
            remote_cmd,
        ]
        return subprocess.run(ssh_args, capture_output=True, timeout=timeout)

    def _push_file(self, local_path: Path, remote_path: str, timeout: float = 300.0):
        """Push a local file to the NAS via SSH cat, or direct copy."""
        if self.direct_path:
            # Direct mode: copy file using filesystem
            import shutil
            local_dest = Path(self._to_local(remote_path))
            local_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(local_path), str(local_dest))
            logger.info(f"Direct copy: {local_path} -> {local_dest}")
            return

        # SSH mode
        remote_dir = str(Path(remote_path).parent)
        self._ssh_cmd(f'mkdir -p "{remote_dir}"')

        cmd = f'cat > "{remote_path}"'
        ssh_args = [
            "ssh",
            "-p", str(self.nas_port),
            "-i", str(self.ssh_key),
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{self.nas_user}@{self.nas_host}",
            cmd,
        ]
        with open(local_path, "rb") as f:
            result = subprocess.run(
                ssh_args, stdin=f, capture_output=True, timeout=timeout
            )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to push to NAS: {remote_path}\n"
                f"stderr: {result.stderr.decode(errors='replace')}"
            )
        logger.info(f"Pushed to NAS: {local_path} -> {remote_path}")

    def _pull_file(self, remote_path: str, local_path: Path, timeout: float = 120.0):
        """Pull a file from the NAS via SSH cat, or direct copy."""
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if self.direct_path:
            import shutil
            src = Path(self._to_local(remote_path))
            if not src.exists():
                raise RuntimeError(f"Source not found (direct mode): {src}")
            shutil.copy2(str(src), str(local_path))
            logger.info(f"Direct pull: {src} -> {local_path} ({local_path.stat().st_size} bytes)")
            return

        cmd = f'cat "{remote_path}"'
        ssh_args = [
            "ssh",
            "-p", str(self.nas_port),
            "-i", str(self.ssh_key),
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{self.nas_user}@{self.nas_host}",
            cmd,
        ]
        with open(local_path, "wb") as f:
            result = subprocess.run(
                ssh_args, stdout=f, stderr=subprocess.PIPE, timeout=timeout
            )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to pull from NAS: {remote_path}\n"
                f"stderr: {result.stderr.decode(errors='replace')}"
            )
        if not local_path.exists() or local_path.stat().st_size == 0:
            raise RuntimeError(f"File pull produced empty result: {local_path}")
        logger.info(
            f"Pulled from NAS: {remote_path} -> {local_path} "
            f"({local_path.stat().st_size} bytes)"
        )

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _track_dir(self, track_title: str) -> str:
        """NAS directory for a track: /volume1/vj-content/Track Title/"""
        return f"{self.base_path}/{track_title}"

    def _shows_dir(self) -> str:
        return f"{self.base_path}/shows"

    def _rsv_dir(self) -> str:
        return f"{self.base_path}/.rsv"

    def get_track_video_path(
        self,
        track_title: str,
        extension: str = ".mov",
        as_resolume_mount: Optional[str] = None,
    ) -> str:
        """Get the video path for a track.

        With as_resolume_mount (default: configured mount), returns the path
        as Resolume on the M4 Mac would see it:
            /Volumes/vj-content/Track Name/Track Name.mov

        Without it, returns the NAS path:
            /volume1/vj-content/Track Name/Track Name.mov
        """
        mount = as_resolume_mount if as_resolume_mount is not None else self.resolume_mount
        if mount:
            return f"{mount}/{track_title}/{track_title}{extension}"
        return f"{self._track_dir(track_title)}/{track_title}{extension}"

    def get_nas_video_path(self, track_title: str, extension: str = ".mov") -> str:
        """Get the NAS-side video path for a track."""
        return f"{self._track_dir(track_title)}/{track_title}{extension}"

    # ------------------------------------------------------------------
    # Folder creation
    # ------------------------------------------------------------------

    def create_track_folder(self, track_title: str) -> str:
        """Create the full folder structure for a new track on NAS.

        Creates:
            <base>/<track_title>/
            <base>/<track_title>/keyframes/
            <base>/<track_title>/stems/

        Returns the NAS path of the track directory.
        """
        track_dir = self._track_dir(track_title)
        cmds = [
            f'mkdir -p "{track_dir}/keyframes"',
            f'mkdir -p "{track_dir}/stems"',
        ]
        result = self._ssh_cmd(" && ".join(cmds))
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create track folder: {track_dir}\n"
                f"stderr: {result.stderr.decode(errors='replace')}"
            )
        logger.info(f"Created track folder: {track_dir}")
        return track_dir

    def ensure_structure(self):
        """Ensure the top-level vj-content structure exists on NAS.

        Creates shows/ and .rsv/ directories if missing.
        """
        cmds = [
            f'mkdir -p "{self._shows_dir()}"',
            f'mkdir -p "{self._rsv_dir()}"',
        ]
        result = self._ssh_cmd(" && ".join(cmds))
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to ensure NAS structure\n"
                f"stderr: {result.stderr.decode(errors='replace')}"
            )
        logger.info("NAS vj-content structure verified")

    # ------------------------------------------------------------------
    # File push operations
    # ------------------------------------------------------------------

    def push_video(
        self, local_path: Path, track_title: str, codec: str = "mov",
        filename: str = "",
    ) -> str:
        """Push a video file to the track's folder on NAS.

        Args:
            local_path: Local file to push.
            track_title: Used as the folder name under base_path.
            codec: File extension (default "mov").
            filename: If provided, used as the filename (instead of track_title).
                      Allows folder name != filename.

        Returns the NAS path of the pushed file.
        """
        ext = f".{codec}" if not codec.startswith(".") else codec
        fname = filename if filename else track_title
        remote_path = f"{self._track_dir(track_title)}/{fname}{ext}"
        self.create_track_folder(track_title)
        self._push_file(local_path, remote_path)
        return remote_path

    def push_preview(
        self, local_path: Path, track_title: str, filename: str = "",
    ) -> str:
        """Push an H.264 preview (with audio) to the track's folder.

        Args:
            local_path: Local file to push.
            track_title: Used as the folder name under base_path.
            filename: If provided, used as the filename (instead of track_title).

        Returns the NAS path.
        """
        fname = filename if filename else track_title
        remote_path = f"{self._track_dir(track_title)}/{fname}.mp4"
        self.create_track_folder(track_title)
        self._push_file(local_path, remote_path)
        return remote_path

    def push_metadata(self, metadata: dict, track_title: str) -> str:
        """Push metadata.json for a track.

        Writes to a local temp file then pushes via SSH cat.
        Returns the NAS path.
        """
        import tempfile

        remote_path = f"{self._track_dir(track_title)}/metadata.json"
        self.create_track_folder(track_title)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(metadata, tmp, indent=2)
            tmp_path = Path(tmp.name)

        try:
            self._push_file(tmp_path, remote_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        return remote_path

    def push_keyframe(
        self, local_path: Path, track_title: str, filename: str
    ) -> str:
        """Push a keyframe image to the track's keyframes/ subfolder.

        Returns the NAS path.
        """
        remote_path = f"{self._track_dir(track_title)}/keyframes/{filename}"
        self._push_file(local_path, remote_path)
        return remote_path

    def push_stem(self, local_path: Path, track_title: str, stem_name: str) -> str:
        """Push a stem WAV to the track's stems/ subfolder.

        Returns the NAS path.
        """
        remote_path = f"{self._track_dir(track_title)}/stems/{stem_name}.wav"
        self._push_file(local_path, remote_path)
        return remote_path

    def push_show(self, local_path: Path, show_name: str) -> str:
        """Push a .avc composition file to shows/.

        Also copies to the top-level for convenience.
        Returns the NAS shows/ path.
        """
        self.ensure_structure()
        shows_path = f"{self._shows_dir()}/{show_name}.avc"
        top_path = f"{self.base_path}/{show_name}.avc"
        self._push_file(local_path, shows_path)
        self._push_file(local_path, top_path)
        return shows_path

    # ------------------------------------------------------------------
    # Registry (.rsv/)
    # ------------------------------------------------------------------

    def _read_registry(self) -> dict:
        """Read registry.json from NAS .rsv/."""
        import tempfile

        registry_path = f"{self._rsv_dir()}/registry.json"
        result = self._ssh_cmd(f'test -f "{registry_path}" && cat "{registry_path}"')
        if result.returncode != 0 or not result.stdout.strip():
            return {"tracks": {}, "version": 1}
        try:
            return json.loads(result.stdout.decode("utf-8"))
        except json.JSONDecodeError:
            logger.warning("Corrupt registry.json, starting fresh")
            return {"tracks": {}, "version": 1}

    def _write_registry(self, registry: dict):
        """Write registry.json to NAS .rsv/."""
        import tempfile

        self.ensure_structure()
        remote_path = f"{self._rsv_dir()}/registry.json"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(registry, tmp, indent=2)
            tmp_path = Path(tmp.name)
        try:
            self._push_file(tmp_path, remote_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def register_track(self, track_title: str, metadata: dict):
        """Register a generated track in the .rsv/registry.json."""
        registry = self._read_registry()
        registry["tracks"][track_title] = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "artist": metadata.get("artist", ""),
            "bpm": metadata.get("bpm"),
            "duration": metadata.get("duration"),
            "nas_path": metadata.get("nas_path", ""),
        }
        self._write_registry(registry)

    def log_generation(self, entry: dict):
        """Append an entry to .rsv/generation_log.json."""
        log_path = f"{self._rsv_dir()}/generation_log.json"
        result = self._ssh_cmd(f'test -f "{log_path}" && cat "{log_path}"')
        if result.returncode == 0 and result.stdout.strip():
            try:
                log = json.loads(result.stdout.decode("utf-8"))
            except json.JSONDecodeError:
                log = []
        else:
            log = []

        entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        log.append(entry)

        import tempfile

        self.ensure_structure()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(log, tmp, indent=2)
            tmp_path = Path(tmp.name)
        try:
            self._push_file(tmp_path, log_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def list_tracks(self) -> list[str]:
        """List all generated track folders on NAS.

        Returns folder names (which are track titles) excluding system dirs.
        """
        result = self._ssh_cmd(f'ls -1 "{self.base_path}"')
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to list NAS tracks\n"
                f"stderr: {result.stderr.decode(errors='replace')}"
            )
        entries = result.stdout.decode("utf-8").strip().splitlines()
        # Exclude system directories and files
        skip = {"shows", ".rsv", ".DS_Store"}
        tracks = []
        for entry in entries:
            entry = entry.strip()
            if not entry or entry in skip or entry.endswith(".avc"):
                continue
            tracks.append(entry)
        return sorted(tracks)

    def track_exists(self, track_title: str) -> bool:
        """Check if a track folder exists on NAS."""
        track_dir = self._track_dir(track_title)
        result = self._ssh_cmd(f'test -d "{track_dir}"')
        return result.returncode == 0

    def track_has_video(
        self, track_title: str, extension: str = ".mov", title: str = "",
    ) -> bool:
        """Check if a track has a generated video file on NAS.

        Args:
            track_title: Used as the folder name under base_path.
            extension: File extension to check for (default .mov).
            title: If provided, used as the filename (instead of track_title).
                   Allows folder name != filename, e.g. folder "Mind Control"
                   with file "Mind Control (Original Mix).mov".
        """
        filename = title if title else track_title
        video_path = f"{self._track_dir(track_title)}/{filename}{extension}"
        result = self._ssh_cmd(f'test -f "{video_path}" && echo EXISTS')
        return result.returncode == 0 and b"EXISTS" in result.stdout

    def get_track_info(self, track_title: str) -> dict:
        """Get info about a track on NAS: files, sizes, metadata.

        Returns a dict with file listing and metadata if available.
        """
        track_dir = self._track_dir(track_title)

        # Check existence
        if not self.track_exists(track_title):
            return {"exists": False, "track_title": track_title}

        # List files with sizes
        result = self._ssh_cmd(
            f'find "{track_dir}" -type f -exec ls -l {{}} \\; 2>/dev/null'
        )
        files = []
        total_size = 0
        if result.returncode == 0:
            for line in result.stdout.decode("utf-8", errors="replace").splitlines():
                parts = line.split()
                if len(parts) >= 9:
                    size = int(parts[4]) if parts[4].isdigit() else 0
                    path = " ".join(parts[8:])
                    # Make path relative to track dir
                    rel = path.replace(track_dir + "/", "", 1)
                    files.append({"path": rel, "size": size})
                    total_size += size

        # Read metadata.json if present
        meta = {}
        meta_result = self._ssh_cmd(f'cat "{track_dir}/metadata.json" 2>/dev/null')
        if meta_result.returncode == 0 and meta_result.stdout.strip():
            try:
                meta = json.loads(meta_result.stdout.decode("utf-8"))
            except json.JSONDecodeError:
                pass

        return {
            "exists": True,
            "track_title": track_title,
            "nas_path": track_dir,
            "resolume_path": self.get_track_video_path(track_title),
            "files": files,
            "total_size": total_size,
            "metadata": meta,
        }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def clean_test_files(self, dry_run: bool = False) -> list[str]:
        """Remove old test/dev folders (test_*, dev_*, tmp_*, debug_*, etc.).

        Returns list of removed directory names.
        """
        result = self._ssh_cmd(f'ls -1 "{self.base_path}"')
        if result.returncode != 0:
            return []

        entries = result.stdout.decode("utf-8").strip().splitlines()
        test_patterns = ("test_", "dev_", "tmp_", "debug_")
        to_remove = []
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            entry_lower = entry.lower()
            if any(entry_lower.startswith(p) for p in test_patterns):
                to_remove.append(entry)

        if dry_run or not to_remove:
            return to_remove

        for dirname in to_remove:
            full_path = f"{self.base_path}/{dirname}"
            rm_result = self._ssh_cmd(f'rm -rf "{full_path}"')
            if rm_result.returncode == 0:
                logger.info(f"Removed test folder: {full_path}")
            else:
                logger.warning(
                    f"Failed to remove {full_path}: "
                    f"{rm_result.stderr.decode(errors='replace')}"
                )

        return to_remove

    # ------------------------------------------------------------------
    # Convenience: pull metadata
    # ------------------------------------------------------------------

    def pull_metadata(self, track_title: str) -> dict:
        """Pull and parse metadata.json for a track. Returns empty dict if missing."""
        meta_path = f"{self._track_dir(track_title)}/metadata.json"
        result = self._ssh_cmd(f'cat "{meta_path}" 2>/dev/null')
        if result.returncode != 0 or not result.stdout.strip():
            return {}
        try:
            return json.loads(result.stdout.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
