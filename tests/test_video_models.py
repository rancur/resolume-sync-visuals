"""Tests for video model support."""
import pytest

from src.generator.video_models import AVAILABLE_VIDEO_MODELS, make_seamless_loop


def test_available_models():
    """Test that video models are defined."""
    assert len(AVAILABLE_VIDEO_MODELS) >= 3
    assert "wan2.1-480p" in AVAILABLE_VIDEO_MODELS
    assert "wan2.1-720p" in AVAILABLE_VIDEO_MODELS
    assert "minimax-live" in AVAILABLE_VIDEO_MODELS


def test_model_has_required_fields():
    """Test each model has required config fields."""
    for name, config in AVAILABLE_VIDEO_MODELS.items():
        assert "id" in config, f"Model {name} missing 'id'"
        assert "max_duration" in config, f"Model {name} missing 'max_duration'"
        assert "cost" in config, f"Model {name} missing 'cost'"
        assert config["max_duration"] > 0
        assert config["cost"] > 0


def test_model_costs_reasonable():
    """Test that model costs are in expected range."""
    for name, config in AVAILABLE_VIDEO_MODELS.items():
        assert 0.01 <= config["cost"] <= 5.0, f"Model {name} cost ${config['cost']} seems wrong"
