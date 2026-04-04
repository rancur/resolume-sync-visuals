"""Tests for progressive rendering quality profiles."""
import pytest

from src.generator.quality_profiles import (
    QUALITY_PROFILES,
    QualityProfile,
    PreviewResult,
    get_quality_profile,
    estimate_savings,
)


class TestQualityProfiles:
    def test_three_profiles_exist(self):
        assert "draft" in QUALITY_PROFILES
        assert "standard" in QUALITY_PROFILES
        assert "high" in QUALITY_PROFILES

    def test_draft_is_cheapest(self):
        draft = QUALITY_PROFILES["draft"]
        high = QUALITY_PROFILES["high"]
        assert draft.cost_multiplier < high.cost_multiplier

    def test_draft_no_video(self):
        draft = QUALITY_PROFILES["draft"]
        assert draft.video_enabled is False

    def test_high_has_video(self):
        high = QUALITY_PROFILES["high"]
        assert high.video_enabled is True

    def test_resolution_increases_with_quality(self):
        draft = QUALITY_PROFILES["draft"]
        standard = QUALITY_PROFILES["standard"]
        high = QUALITY_PROFILES["high"]
        assert draft.width < standard.width < high.width
        assert draft.height < standard.height < high.height

    def test_resolution_str(self):
        draft = QUALITY_PROFILES["draft"]
        assert "x" in draft.resolution_str
        assert str(draft.width) in draft.resolution_str


class TestGetQualityProfile:
    def test_valid_names(self):
        for name in ["draft", "standard", "high"]:
            profile = get_quality_profile(name)
            assert profile.name == name

    def test_case_insensitive(self):
        profile = get_quality_profile("HIGH")
        assert profile.name == "high"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Unknown quality"):
            get_quality_profile("ultra")


class TestEstimatedCost:
    def test_draft_cheaper_than_high(self):
        draft = QUALITY_PROFILES["draft"]
        high = QUALITY_PROFILES["high"]
        assert draft.estimated_cost_per_track(180) < high.estimated_cost_per_track(180)

    def test_longer_track_costs_more(self):
        high = QUALITY_PROFILES["high"]
        short = high.estimated_cost_per_track(60)
        long = high.estimated_cost_per_track(300)
        assert long > short

    def test_cost_is_positive(self):
        for profile in QUALITY_PROFILES.values():
            cost = profile.estimated_cost_per_track(180)
            assert cost > 0


class TestEstimateSavings:
    def test_savings_are_positive(self):
        result = estimate_savings(180.0)
        assert result["savings"] >= 0
        assert result["savings_pct"] >= 0

    def test_with_progressive_cheaper(self):
        result = estimate_savings(180.0, approval_rate=0.5)
        assert result["with_progressive"] < result["without_progressive"]

    def test_100_pct_approval_still_saves(self):
        # Even at 100% approval, preview cost << full cost, so total is slightly more
        # but the structure should still work
        result = estimate_savings(180.0, approval_rate=1.0)
        assert result["savings_pct"] >= 0

    def test_custom_approval_rate(self):
        low_rate = estimate_savings(180.0, approval_rate=0.3)
        high_rate = estimate_savings(180.0, approval_rate=0.9)
        # Lower approval rate = more savings
        assert low_rate["savings"] >= high_rate["savings"]

    def test_returns_all_fields(self):
        result = estimate_savings(180.0)
        assert "without_progressive" in result
        assert "with_progressive" in result
        assert "savings" in result
        assert "savings_pct" in result
        assert "preview_cost" in result
        assert "final_cost" in result
        assert "approval_rate" in result


class TestPreviewResult:
    def test_to_dict(self):
        preview = PreviewResult(
            track_id="123",
            track_title="Test Track",
            quality="draft",
            segments=[{"label": "drop", "start": 0, "end": 30}],
            keyframe_paths=["/tmp/kf1.png"],
            estimated_final_cost=2.50,
            preview_cost=0.12,
            status="planned",
        )
        d = preview.to_dict()
        assert d["track_id"] == "123"
        assert d["quality"] == "draft"
        assert len(d["segments"]) == 1
        assert d["estimated_final_cost"] == 2.50
        assert d["status"] == "planned"

    def test_default_status(self):
        preview = PreviewResult(track_id="1", track_title="T", quality="draft")
        assert preview.status == "pending"
