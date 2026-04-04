"""
Auto-update system — checks GitHub for new releases and can update the Docker container.
"""
import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional

import httpx

from src import __version__

logger = logging.getLogger(__name__)

GITHUB_REPO = "rancur/resolume-sync-visuals"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
DOCKER_IMAGE = "ghcr.io/rancur/resolume-sync-visuals"


class AutoUpdater:
    """Checks GitHub for new releases and can update the Docker container."""

    def __init__(self):
        self._last_check: Optional[datetime] = None
        self._cached_latest: Optional[dict] = None
        self._cache_ttl_seconds = 300  # 5 min cache

    @property
    def current_version(self) -> str:
        return __version__

    def check_for_updates(self) -> dict:
        """Check GitHub API for latest release.

        Returns:
            dict with keys: current, latest, update_available, changelog, published_at
        """
        now = datetime.now(timezone.utc)

        # Use cache if fresh
        if (
            self._cached_latest
            and self._last_check
            and (now - self._last_check).total_seconds() < self._cache_ttl_seconds
        ):
            return self._cached_latest

        result = {
            "current": self.current_version,
            "latest": self.current_version,
            "update_available": False,
            "changelog": "",
            "published_at": "",
            "html_url": "",
        }

        try:
            resp = httpx.get(
                GITHUB_API,
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                latest_tag = data.get("tag_name", "").lstrip("v")
                result["latest"] = latest_tag
                result["update_available"] = self._is_newer(latest_tag, self.current_version)
                result["changelog"] = data.get("body", "")
                result["published_at"] = data.get("published_at", "")
                result["html_url"] = data.get("html_url", "")
            elif resp.status_code == 404:
                logger.info("No releases found on GitHub")
            else:
                logger.warning("GitHub API returned %d", resp.status_code)
        except Exception as e:
            logger.error("Failed to check for updates: %s", e)

        self._cached_latest = result
        self._last_check = now
        return result

    def update(self) -> dict:
        """Pull latest Docker image and restart container.

        Returns:
            dict with keys: success, message, old_version, new_version
        """
        old_version = self.current_version
        result = {
            "success": False,
            "message": "",
            "old_version": old_version,
            "new_version": old_version,
        }

        # Check if running in Docker
        if not self._is_docker():
            result["message"] = (
                "Not running in Docker. For non-Docker installs, update via: "
                "git pull && pip install -e . && restart the server"
            )
            return result

        try:
            # Pull latest image
            logger.info("Pulling latest Docker image: %s", DOCKER_IMAGE)
            pull_result = subprocess.run(
                ["docker", "pull", f"{DOCKER_IMAGE}:latest"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if pull_result.returncode != 0:
                result["message"] = f"Docker pull failed: {pull_result.stderr.strip()}"
                return result

            # Find our container name
            container_name = self._get_container_name()
            if not container_name:
                result["message"] = (
                    "Image pulled successfully. Restart the container manually or "
                    "use docker-compose up -d to apply the update."
                )
                result["success"] = True
                return result

            # Restart via docker-compose if available
            compose_result = subprocess.run(
                ["docker", "compose", "up", "-d", "--force-recreate"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if compose_result.returncode == 0:
                result["success"] = True
                result["message"] = "Update pulled and container recreated. Restarting..."
            else:
                # Fallback: just report success on pull
                result["success"] = True
                result["message"] = (
                    "Image pulled. Run 'docker compose up -d --force-recreate' to apply."
                )

        except subprocess.TimeoutExpired:
            result["message"] = "Update timed out. Try manually."
        except FileNotFoundError:
            result["message"] = "Docker CLI not found. Update manually."
        except Exception as e:
            result["message"] = f"Update failed: {e}"
            logger.error("Update error: %s", e)

        return result

    def _is_newer(self, latest: str, current: str) -> bool:
        """Compare semver strings. Returns True if latest > current."""
        try:
            latest_parts = [int(x) for x in latest.split(".")]
            current_parts = [int(x) for x in current.split(".")]
            return latest_parts > current_parts
        except (ValueError, AttributeError):
            return latest != current

    def _is_docker(self) -> bool:
        """Check if we're running inside a Docker container."""
        return (
            os.path.exists("/.dockerenv")
            or os.environ.get("DOCKER_CONTAINER") == "1"
        )

    def _get_container_name(self) -> Optional[str]:
        """Try to determine our Docker container name."""
        try:
            hostname = os.environ.get("HOSTNAME", "")
            if hostname:
                result = subprocess.run(
                    ["docker", "inspect", "--format", "{{.Name}}", hostname],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    return result.stdout.strip().lstrip("/")
        except Exception:
            pass
        return None


# Singleton
_updater: Optional[AutoUpdater] = None


def get_updater() -> AutoUpdater:
    global _updater
    if _updater is None:
        _updater = AutoUpdater()
    return _updater
