"""
Version tracking and rollback for generated videos.

Every generation for a track creates a new version. Tracks maintain a
version history with metadata (model, brand hash, quality score, etc.).

Storage layout on NAS:
  <track>/
    v1/
      video.mov
      metadata.json
    v2/
      video.mov
      metadata.json
    latest -> v2   (symlink to current version)

The .rsv registry tracks version history per track.
"""
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_VERSIONS = 3


@dataclass
class VideoVersion:
    """Metadata for one version of a generated video."""
    version: int
    track_title: str
    created_at: str
    model: str = ""
    brand: str = ""
    brand_hash: str = ""
    prompt_hash: str = ""
    quality_score: int = 0
    file_path: str = ""
    file_size: int = 0
    duration: float = 0.0
    resolution: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "track_title": self.track_title,
            "created_at": self.created_at,
            "model": self.model,
            "brand": self.brand,
            "brand_hash": self.brand_hash,
            "prompt_hash": self.prompt_hash,
            "quality_score": self.quality_score,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "duration": self.duration,
            "resolution": self.resolution,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VideoVersion":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class VersionHistory:
    """Version history for a single track."""
    track_title: str
    versions: list[VideoVersion] = field(default_factory=list)
    current_version: int = 0
    max_versions: int = DEFAULT_MAX_VERSIONS

    @property
    def latest(self) -> Optional[VideoVersion]:
        if not self.versions:
            return None
        return next(
            (v for v in self.versions if v.version == self.current_version),
            self.versions[-1],
        )

    def to_dict(self) -> dict:
        return {
            "track_title": self.track_title,
            "versions": [v.to_dict() for v in self.versions],
            "current_version": self.current_version,
            "max_versions": self.max_versions,
            "total_versions": len(self.versions),
        }


class VersionTracker:
    """Manages version history for generated videos.

    Uses a JSON file per track for persistence (no external DB needed).
    """

    def __init__(self, registry_dir: Optional[Path] = None):
        self.registry_dir = Path(registry_dir) if registry_dir else Path("output/.versions")
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    def _history_path(self, track_title: str) -> Path:
        """Path to the version history JSON for a track."""
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in track_title)
        return self.registry_dir / f"{safe_name}.json"

    def get_history(self, track_title: str) -> VersionHistory:
        """Get version history for a track.

        Returns empty history if no versions exist yet.
        """
        path = self._history_path(track_title)
        if not path.exists():
            return VersionHistory(track_title=track_title)

        try:
            data = json.loads(path.read_text())
            history = VersionHistory(
                track_title=data.get("track_title", track_title),
                current_version=data.get("current_version", 0),
                max_versions=data.get("max_versions", DEFAULT_MAX_VERSIONS),
            )
            for vd in data.get("versions", []):
                history.versions.append(VideoVersion.from_dict(vd))
            return history
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Corrupt version history for '{track_title}': {e}")
            return VersionHistory(track_title=track_title)

    def _save_history(self, history: VersionHistory):
        """Persist version history to disk."""
        path = self._history_path(history.track_title)
        path.write_text(json.dumps(history.to_dict(), indent=2))

    def add_version(
        self,
        track_title: str,
        model: str = "",
        brand: str = "",
        brand_hash: str = "",
        prompt_hash: str = "",
        quality_score: int = 0,
        file_path: str = "",
        file_size: int = 0,
        duration: float = 0.0,
        resolution: str = "",
        notes: str = "",
    ) -> VideoVersion:
        """Record a new version for a track.

        Increments the version number, adds the entry, and auto-cleans
        old versions if over the max.

        Returns:
            The new VideoVersion.
        """
        history = self.get_history(track_title)

        # Determine next version number
        if history.versions:
            next_version = max(v.version for v in history.versions) + 1
        else:
            next_version = 1

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        version = VideoVersion(
            version=next_version,
            track_title=track_title,
            created_at=now,
            model=model,
            brand=brand,
            brand_hash=brand_hash,
            prompt_hash=prompt_hash,
            quality_score=quality_score,
            file_path=file_path,
            file_size=file_size,
            duration=duration,
            resolution=resolution,
            notes=notes,
        )

        history.versions.append(version)
        history.current_version = next_version

        # Auto-cleanup old versions
        self._enforce_max_versions(history)

        self._save_history(history)
        logger.info(
            f"Version {next_version} added for '{track_title}' "
            f"(model={model}, score={quality_score})"
        )
        return version

    def rollback(self, track_title: str, version: int) -> Optional[VideoVersion]:
        """Point 'current' at a specific version.

        Does NOT delete newer versions -- just changes which version is active.

        Returns:
            The now-current VideoVersion, or None if version not found.
        """
        history = self.get_history(track_title)
        target = next((v for v in history.versions if v.version == version), None)

        if not target:
            logger.warning(f"Version {version} not found for '{track_title}'")
            return None

        history.current_version = version
        self._save_history(history)
        logger.info(f"Rolled back '{track_title}' to version {version}")
        return target

    def list_versions(self, track_title: str) -> list[dict]:
        """List all versions for a track with current marker.

        Returns list of version dicts with added 'is_current' field.
        """
        history = self.get_history(track_title)
        result = []
        for v in history.versions:
            d = v.to_dict()
            d["is_current"] = (v.version == history.current_version)
            result.append(d)
        return result

    def delete_version(self, track_title: str, version: int) -> bool:
        """Delete a specific version.

        Cannot delete the current version. Deletes the file if it exists.

        Returns:
            True if deleted, False if not found or is current.
        """
        history = self.get_history(track_title)

        if version == history.current_version:
            logger.warning(f"Cannot delete current version {version}")
            return False

        target = next((v for v in history.versions if v.version == version), None)
        if not target:
            return False

        # Delete file
        if target.file_path:
            fp = Path(target.file_path)
            if fp.exists():
                fp.unlink()

        history.versions = [v for v in history.versions if v.version != version]
        self._save_history(history)
        logger.info(f"Deleted version {version} for '{track_title}'")
        return True

    def _enforce_max_versions(self, history: VersionHistory):
        """Remove oldest versions exceeding max_versions."""
        while len(history.versions) > history.max_versions:
            # Remove oldest non-current version
            oldest = None
            for v in sorted(history.versions, key=lambda v: v.version):
                if v.version != history.current_version:
                    oldest = v
                    break

            if oldest is None:
                break  # All versions are current (shouldn't happen)

            if oldest.file_path:
                fp = Path(oldest.file_path)
                if fp.exists():
                    fp.unlink()

            history.versions = [
                v for v in history.versions if v.version != oldest.version
            ]
            logger.info(
                f"Auto-cleaned version {oldest.version} for '{history.track_title}'"
            )

    def get_all_tracks(self) -> list[str]:
        """List all tracked track titles."""
        tracks = []
        for path in self.registry_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                tracks.append(data.get("track_title", path.stem))
            except (json.JSONDecodeError, KeyError):
                continue
        return sorted(tracks)

    def total_disk_usage(self) -> int:
        """Calculate total disk usage across all versions (bytes)."""
        total = 0
        for path in self.registry_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                for v in data.get("versions", []):
                    total += v.get("file_size", 0)
            except (json.JSONDecodeError, KeyError):
                continue
        return total
