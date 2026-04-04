"""
Tests for new features: auto-update, video proxy, vocals, style transfer, fingerprints.
"""
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Use a temp directory for the database so tests don't touch real data."""
    monkeypatch.setenv("RSV_DB_PATH", str(tmp_path))
    import server.config as cfg
    cfg._settings = None
    yield
    cfg._settings = None


@pytest.fixture
def client():
    from server.main import app
    with TestClient(app) as c:
        yield c


# ── Issue #67: Auto-update system ──

class TestAutoUpdater:
    def test_version_endpoint(self, client):
        resp = client.get("/api/system/version")
        assert resp.status_code == 200
        data = resp.json()
        assert "current" in data
        assert "latest" in data
        assert "update_available" in data

    def test_docker_status_endpoint(self, client):
        resp = client.get("/api/system/docker")
        assert resp.status_code == 200
        data = resp.json()
        assert "running_in_docker" in data
        assert data["running_in_docker"] is False  # Not in Docker during tests

    def test_release_notes_endpoint(self, client):
        resp = client.get("/api/system/release-notes")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "changelog" in data

    def test_update_not_in_docker(self, client):
        resp = client.post("/api/system/update")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Not running in Docker" in data["message"]

    def test_version_comparison(self):
        from server.services.updater import AutoUpdater
        updater = AutoUpdater()
        assert updater._is_newer("1.2.0", "1.1.0") is True
        assert updater._is_newer("1.0.0", "1.1.0") is False
        assert updater._is_newer("2.0.0", "1.9.9") is True
        assert updater._is_newer("1.0.0", "1.0.0") is False

    def test_version_cache(self):
        from server.services.updater import AutoUpdater
        updater = AutoUpdater()
        with patch("httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "tag_name": "v1.0.0",
                "body": "Release notes",
                "published_at": "2026-01-01",
                "html_url": "https://example.com",
            }
            mock_get.return_value = mock_resp

            result1 = updater.check_for_updates()
            result2 = updater.check_for_updates()

            # Second call should use cache (only 1 HTTP request)
            assert mock_get.call_count == 1
            assert result1["latest"] == "1.0.0"


# ── Issue #65: Video proxy ──

class TestVideoProxy:
    def test_video_preview_not_found(self, client):
        """Should 404 when NAS file doesn't exist."""
        with patch("server.routers.videos._check_nas_file", return_value=None):
            resp = client.get("/api/videos/Nonexistent%20Track/preview")
            assert resp.status_code == 404

    def test_video_info_endpoint(self, client):
        """Should return info about video files."""
        with patch("server.routers.videos._check_nas_file", return_value=None):
            resp = client.get("/api/videos/Test%20Track/info")
            assert resp.status_code == 200
            data = resp.json()
            assert data["track_name"] == "Test Track"
            assert data["has_preview"] is False

    def test_video_info_with_files(self, client):
        """Should show file info when files exist."""
        def mock_check(path):
            if path.endswith(".mp4"):
                return 5000000  # 5MB
            if path.endswith(".mov"):
                return 50000000  # 50MB
            return None

        with patch("server.routers.videos._check_nas_file", side_effect=mock_check):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                resp = client.get("/api/videos/Test%20Track/info")
                assert resp.status_code == 200
                data = resp.json()
                assert data["has_preview"] is True
                assert data["has_dxv"] is True
                assert data["preview_size_mb"] == pytest.approx(4.77, abs=0.1)

    def test_thumbnail_not_found(self, client):
        with patch("server.routers.videos._check_nas_file", return_value=None):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                resp = client.get("/api/videos/Nonexistent/thumbnail")
                assert resp.status_code == 404


# ── Issue #34: Style transfer reference images ──

class TestStyleTransfer:
    def test_list_reference_images_empty(self, client):
        resp = client.get("/api/brands/will_see/reference-images")
        assert resp.status_code == 200
        data = resp.json()
        assert data["brand"] == "will_see"
        assert isinstance(data["references"], list)

    def test_upload_reference_image(self, client, tmp_path):
        """Should upload and store a reference image."""
        # Create a minimal valid PNG (1x1 pixel)
        import struct
        import zlib

        def make_png():
            sig = b'\x89PNG\r\n\x1a\n'
            ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data)
            ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
            raw = zlib.compress(b'\x00\x00\x00\x00')
            idat_crc = zlib.crc32(b'IDAT' + raw)
            idat = struct.pack('>I', len(raw)) + b'IDAT' + raw + struct.pack('>I', idat_crc)
            iend_crc = zlib.crc32(b'IEND')
            iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
            return sig + ihdr + idat + iend

        png_data = make_png()
        resp = client.post(
            "/api/brands/will_see/reference-image",
            files={"file": ("test_ref.png", io.BytesIO(png_data), "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["uploaded"] is True
        assert data["brand"] == "will_see"
        assert data["total_references"] >= 1

    def test_upload_invalid_type(self, client):
        resp = client.post(
            "/api/brands/will_see/reference-image",
            files={"file": ("test.txt", io.BytesIO(b"not an image"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_brand_not_found(self, client):
        resp = client.post(
            "/api/brands/nonexistent_xyz/reference-image",
            files={"file": ("test.png", io.BytesIO(b"fake"), "image/png")},
        )
        assert resp.status_code == 404


# ── Issue #57: Audio fingerprinting ──

class TestAudioFingerprinting:
    def test_registry_fingerprint_storage(self, tmp_path):
        from src.tracking.registry import RenderRegistry

        reg = RenderRegistry(db_path=tmp_path / "registry.db")
        reg.store_fingerprint(
            fingerprint="abc123def456",
            audio_path="/music/track.wav",
            track_name="Test Track",
            artist="Test Artist",
            duration_sec=180.0,
        )

        result = reg.lookup_fingerprint("abc123def456")
        assert result is not None
        assert result["track_name"] == "Test Track"
        assert result["artist"] == "Test Artist"

    def test_registry_fingerprint_not_found(self, tmp_path):
        from src.tracking.registry import RenderRegistry
        reg = RenderRegistry(db_path=tmp_path / "registry.db")
        assert reg.lookup_fingerprint("nonexistent") is None

    def test_registry_all_fingerprints(self, tmp_path):
        from src.tracking.registry import RenderRegistry
        reg = RenderRegistry(db_path=tmp_path / "registry.db")

        reg.store_fingerprint("fp1", "/a.wav", "Track A")
        reg.store_fingerprint("fp2", "/b.wav", "Track B")

        all_fps = reg.get_all_fingerprints()
        assert len(all_fps) == 2

    def test_registry_fingerprint_upsert(self, tmp_path):
        from src.tracking.registry import RenderRegistry
        reg = RenderRegistry(db_path=tmp_path / "registry.db")

        reg.store_fingerprint("fp1", "/a.wav", "Track A", artist="Old")
        reg.store_fingerprint("fp1", "/a.wav", "Track A", artist="New")

        result = reg.lookup_fingerprint("fp1")
        assert result["artist"] == "New"
        assert len(reg.get_all_fingerprints()) == 1


# ── Issue #40: Vocal isolation ──

class TestVocalIsolation:
    def test_vocal_analysis(self):
        """Test the vocal analysis function directly."""
        from server.routers.vocals import _get_vocal_analysis

        sr = 22050
        duration = 2.0
        t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
        # Simulate vocals with amplitude envelope
        audio = (0.5 * np.sin(2 * np.pi * 400 * t) * np.exp(-((t - 1) ** 2) / 0.3)).astype(np.float32)

        result = _get_vocal_analysis(audio, sr)

        assert "duration" in result
        assert "active_regions" in result
        assert "energy" in result
        assert result["duration"] == pytest.approx(duration, abs=0.1)
        assert isinstance(result["energy"], list)
        assert result["fps"] == 30.0
        assert result["mean_energy"] >= 0


# ── Issue #66: Setup wizard ──

class TestSetupWizard:
    def test_setup_status(self, client):
        resp = client.get("/api/setup/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "setup_complete" in data
        assert "sections" in data

    def test_dismiss_and_reset(self, client):
        # Dismiss
        resp = client.post("/api/setup/dismiss")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Check dismissed
        resp = client.get("/api/setup/status")
        assert resp.json()["setup_dismissed"] is True

        # Reset
        resp = client.post("/api/setup/reset")
        assert resp.status_code == 200

        # Check not dismissed
        resp = client.get("/api/setup/status")
        # It may still be complete due to default settings
        assert resp.json()["setup_dismissed"] is False
