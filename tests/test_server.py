"""
Tests for the FastAPI server.
Uses TestClient for synchronous endpoint testing.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Use a temp directory for the database so tests don't touch real data."""
    monkeypatch.setenv("RSV_DB_PATH", str(tmp_path))
    # Reset the settings singleton so it picks up the new env
    import server.config as cfg
    cfg._settings = None
    yield
    cfg._settings = None


@pytest.fixture
def client():
    from server.main import app
    with TestClient(app) as c:
        yield c


# ── Health ──

def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "rsv"
    assert "websocket_clients" in data


# ── Jobs ──

def test_list_jobs_empty(client):
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["jobs"] == []


def test_create_job_track_not_found(client):
    """Creating a job for a non-existent track should 404."""
    with patch("server.routers.generation.get_lexicon_service") as mock_svc:
        mock_svc.return_value.get_track.return_value = None
        resp = client.post("/api/jobs", json={"track_id": "99999"})
        assert resp.status_code == 404


def test_create_job_success(client):
    """Creating a job with a valid track should return the job."""
    fake_track = {"id": "1", "title": "Test Song", "artist": "DJ Test", "bpm": 128}
    with patch("server.routers.generation.get_lexicon_service") as mock_svc:
        mock_svc.return_value.get_track.return_value = fake_track
        resp = client.post("/api/jobs", json={"track_id": "1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["track_title"] == "Test Song"
        assert data["status"] == "queued"
        job_id = data["id"]

    # Verify it shows up in list
    resp2 = client.get("/api/jobs")
    assert resp2.status_code == 200
    assert len(resp2.json()["jobs"]) == 1


def test_cancel_job(client):
    """Cancelling a queued job should succeed."""
    fake_track = {"id": "2", "title": "Cancel Me", "artist": "Test", "bpm": 140}
    with patch("server.routers.generation.get_lexicon_service") as mock_svc:
        mock_svc.return_value.get_track.return_value = fake_track
        resp = client.post("/api/jobs", json={"track_id": "2"})
        job_id = resp.json()["id"]

    resp2 = client.delete(f"/api/jobs/{job_id}")
    assert resp2.status_code == 200
    assert resp2.json()["cancelled"] is True

    # Verify status changed
    resp3 = client.get(f"/api/jobs/{job_id}")
    assert resp3.json()["status"] == "cancelled"


def test_cancel_nonexistent_job(client):
    resp = client.delete("/api/jobs/doesnotexist")
    assert resp.status_code == 400


# ── Bulk jobs ──

def test_bulk_jobs(client):
    fake_track = {"id": "10", "title": "Bulk Track", "artist": "Bulk", "bpm": 130}
    with patch("server.routers.generation.get_lexicon_service") as mock_svc:
        mock_svc.return_value.get_track.side_effect = (
            lambda tid: fake_track if tid == "10" else None
        )
        resp = client.post(
            "/api/jobs/bulk",
            json={"track_ids": ["10", "999"], "brand": "will_see"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["jobs"]) == 1
        assert len(data["errors"]) == 1


# ── Brands ──

def test_list_brands(client):
    resp = client.get("/api/brands")
    assert resp.status_code == 200
    data = resp.json()
    assert "brands" in data
    names = [b["name"] for b in data["brands"]]
    assert "will_see" in names


def test_get_brand(client):
    resp = client.get("/api/brands/will_see")
    assert resp.status_code == 200
    data = resp.json()
    # Brand YAML should have a name or sections key
    assert isinstance(data, dict)


def test_get_brand_not_found(client):
    resp = client.get("/api/brands/nonexistent_brand_xyz")
    assert resp.status_code == 404


# ── Models ──

def test_list_models(client):
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "video_models" in data
    assert "image_models" in data
    assert len(data["video_models"]) > 0


def test_default_model(client):
    resp = client.get("/api/models/default")
    assert resp.status_code == 200
    data = resp.json()
    assert "video_model" in data
    assert "image_model" in data


# ── Settings ──

def test_get_settings(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "env" in data
    assert "db" in data
    # API keys should be masked
    fal = data["env"]["fal_key"]
    assert "..." in fal or fal == ""


def test_update_settings(client):
    resp = client.put(
        "/api/settings",
        json={"settings": {"custom_key": "custom_value"}},
    )
    assert resp.status_code == 200
    assert "custom_key" in resp.json()["updated"]


# ── Budget ──

def test_budget_summary(client):
    resp = client.get("/api/budget/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_cost" in data


def test_budget_projection(client):
    resp = client.get("/api/budget/projection?days=30")
    assert resp.status_code == 200
    data = resp.json()
    assert "projected_cost" in data


# ── Logs ──

def test_list_runs(client):
    resp = client.get("/api/logs/runs")
    assert resp.status_code == 200
    assert "runs" in resp.json()


def test_get_run_not_found(client):
    resp = client.get("/api/logs/runs/nonexistent_run_id")
    assert resp.status_code == 404


# ── Preview ──

def test_preview_keyframes_not_found(client):
    with patch("server.routers.preview.get_lexicon_service") as mock_svc:
        mock_svc.return_value.get_track.return_value = None
        resp = client.post("/api/preview/999/keyframes", json={})
        assert resp.status_code == 404


def test_preview_keyframes_success(client):
    fake_track = {"id": "5", "title": "Preview Track", "artist": "Test", "bpm": 126}
    with patch("server.routers.preview.get_lexicon_service") as mock_svc:
        mock_svc.return_value.get_track.return_value = fake_track
        resp = client.post("/api/preview/5/keyframes", json={"brand": "will_see"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "planned"


# ── Error handling ──

def test_tracks_lexicon_unavailable(client):
    """When Lexicon API is down, tracks endpoint should return 502, not crash."""
    with patch("server.routers.tracks.get_lexicon_service") as mock_svc:
        mock_svc.return_value.get_tracks.side_effect = ConnectionError("Connection refused")
        resp = client.get("/api/tracks")
        assert resp.status_code == 502
        assert "unavailable" in resp.json()["detail"].lower()


def test_playlist_tracks_lexicon_unavailable(client):
    """When Lexicon API is down, playlist tracks should return 502."""
    with patch("server.routers.tracks.get_lexicon_service") as mock_svc:
        mock_svc.return_value.get_playlist_tracks.side_effect = ConnectionError("Connection refused")
        resp = client.get("/api/playlists/1/tracks")
        assert resp.status_code == 502


# ── WebSocket ──

def test_websocket_ping(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text("ping")
        data = ws.receive_text()
        assert json.loads(data)["type"] == "pong"
