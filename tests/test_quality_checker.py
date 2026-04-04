"""Tests for automatic quality checks on generated videos."""
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.quality_checker import (
    CHECK_WEIGHTS,
    CheckResult,
    QualityReport,
    run_quality_checks,
    _check_black_frames,
    _check_color_banding,
    _check_duration_accuracy,
    _check_frozen_video,
    _check_technical,
    _check_temporal_coherence,
    _parse_fps,
    _probe_video,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_test_video(duration: float = 3.0, width: int = 320, height: int = 240) -> Path:
    """Create a minimal test video using ffmpeg."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i",
                f"color=c=blue:s={width}x{height}:d={duration}:r=10",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                tmp.name,
            ],
            capture_output=True, timeout=30,
        )
        return Path(tmp.name)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("ffmpeg not available")


def _make_black_video(duration: float = 3.0) -> Path:
    """Create a near-black test video."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i",
                f"color=c=black:s=320x240:d={duration}:r=10",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                tmp.name,
            ],
            capture_output=True, timeout=30,
        )
        return Path(tmp.name)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("ffmpeg not available")


# ── CheckResult ──────────────────────────────────────────────────────

class TestCheckResult:
    def test_basic_creation(self):
        cr = CheckResult(name="test", score=85, passed=True, details="ok")
        assert cr.name == "test"
        assert cr.score == 85
        assert cr.passed

    def test_severity_default(self):
        cr = CheckResult(name="test", score=50, passed=True)
        assert cr.severity == "info"


# ── QualityReport ────────────────────────────────────────────────────

class TestQualityReport:
    def test_to_dict(self):
        report = QualityReport(
            video_path="/tmp/test.mp4",
            overall_score=75,
            passed=True,
            checks=[CheckResult(name="test", score=75, passed=True, details="ok")],
        )
        d = report.to_dict()
        assert d["video_path"] == "/tmp/test.mp4"
        assert d["overall_score"] == 75
        assert len(d["checks"]) == 1
        assert d["checks"][0]["name"] == "test"

    def test_default_values(self):
        report = QualityReport(video_path="/tmp/test.mp4")
        assert report.overall_score == 0
        assert report.passed is False
        assert report.should_regenerate is False
        assert report.retry_count == 0


# ── _parse_fps ───────────────────────────────────────────────────────

class TestParseFps:
    def test_fraction(self):
        assert _parse_fps("30/1") == 30.0

    def test_decimal(self):
        assert abs(_parse_fps("29.97") - 29.97) < 0.01

    def test_invalid_returns_default(self):
        assert _parse_fps("invalid") == 30.0

    def test_zero_denominator(self):
        assert _parse_fps("30/0") == 30.0


# ── _check_technical ─────────────────────────────────────────────────

class TestCheckTechnical:
    def test_matching_resolution(self):
        info = {"width": 1920, "height": 1080, "size_bytes": 1000000, "codec": "h264"}
        result = _check_technical(info, 1920, 1080)
        assert result.score == 100
        assert result.passed

    def test_wrong_resolution(self):
        info = {"width": 1280, "height": 720, "size_bytes": 1000000, "codec": "h264"}
        result = _check_technical(info, 1920, 1080)
        assert result.score < 100
        assert "Resolution" in result.details

    def test_tiny_file(self):
        info = {"width": 1920, "height": 1080, "size_bytes": 100, "codec": "h264"}
        result = _check_technical(info, 1920, 1080)
        assert result.score < 70

    def test_no_codec(self):
        info = {"width": 1920, "height": 1080, "size_bytes": 1000000, "codec": ""}
        result = _check_technical(info, 1920, 1080)
        assert result.score < 100


# ── _check_duration_accuracy ─────────────────────────────────────────

class TestCheckDurationAccuracy:
    def test_exact_match(self):
        info = {"duration": 180.0}
        result = _check_duration_accuracy(info, 180.0)
        assert result.score == 100
        assert result.passed

    def test_small_difference(self):
        info = {"duration": 182.0}
        result = _check_duration_accuracy(info, 180.0)
        assert result.score >= 85

    def test_large_difference(self):
        info = {"duration": 120.0}
        result = _check_duration_accuracy(info, 180.0)
        assert result.score < 50

    def test_no_expected_duration(self):
        info = {"duration": 180.0}
        result = _check_duration_accuracy(info, None)
        assert result.passed
        assert result.score >= 80

    def test_zero_duration(self):
        info = {"duration": 0.0}
        result = _check_duration_accuracy(info, 180.0)
        assert result.score == 0
        assert not result.passed


# ── _check_color_banding ─────────────────────────────────────────────

class TestCheckColorBanding:
    def test_high_bitrate(self):
        info = {
            "pix_fmt": "yuv420p",
            "bitrate": 50_000_000,
            "duration": 10.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
        }
        result = _check_color_banding(Path("/fake.mp4"), info, 5)
        assert result.score >= 70

    def test_low_bitrate_flags(self):
        info = {
            "pix_fmt": "yuv420p",
            "bitrate": 500_000,  # 500kbps for 1080p = very low
            "duration": 10.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
        }
        result = _check_color_banding(Path("/fake.mp4"), info, 5)
        assert result.score < 90

    def test_10bit_no_penalty(self):
        info = {
            "pix_fmt": "yuv420p10le",
            "bitrate": 10_000_000,
            "duration": 10.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
        }
        result = _check_color_banding(Path("/fake.mp4"), info, 5)
        assert result.score >= 90


# ── check_weights ────────────────────────────────────────────────────

class TestCheckWeights:
    def test_weights_sum_to_one(self):
        total = sum(CHECK_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01, f"Weights sum to {total}, expected 1.0"

    def test_all_checks_have_weights(self):
        expected = {"black_frames", "frozen_video", "color_banding",
                    "temporal_coherence", "duration_accuracy", "technical"}
        assert set(CHECK_WEIGHTS.keys()) == expected


# ── Integration: run_quality_checks ──────────────────────────────────

class TestRunQualityChecks:
    def test_nonexistent_file(self):
        report = run_quality_checks("/tmp/nonexistent_video_xyz.mp4")
        assert not report.passed
        assert report.overall_score == 0
        assert report.should_regenerate

    def test_nonexistent_file_max_retries(self):
        report = run_quality_checks(
            "/tmp/nonexistent_video_xyz.mp4",
            retry_count=2, max_retries=2,
        )
        assert not report.should_regenerate  # At max retries

    def test_real_video_passes(self):
        video = _make_test_video(duration=3.0)
        report = run_quality_checks(
            video,
            expected_duration=3.0,
            expected_width=320,
            expected_height=240,
            sample_points=3,
        )
        # Blue video should pass most checks
        assert report.overall_score > 40
        assert len(report.checks) >= 5

    def test_black_video_flagged(self):
        video = _make_black_video(duration=3.0)
        report = run_quality_checks(
            video,
            expected_duration=3.0,
            expected_width=320,
            expected_height=240,
            sample_points=3,
        )
        # Black video should get low black_frames score
        black_check = next(
            (c for c in report.checks if c.name == "black_frames"), None
        )
        assert black_check is not None
        assert black_check.score < 50

    def test_report_has_all_checks(self):
        video = _make_test_video(duration=2.0)
        report = run_quality_checks(
            video,
            expected_width=320,
            expected_height=240,
            sample_points=3,
        )
        check_names = {c.name for c in report.checks}
        assert "technical" in check_names
        assert "duration_accuracy" in check_names
        assert "black_frames" in check_names
        assert "frozen_video" in check_names

    def test_to_dict_serializable(self):
        video = _make_test_video(duration=2.0)
        report = run_quality_checks(
            video,
            expected_width=320,
            expected_height=240,
            sample_points=3,
        )
        d = report.to_dict()
        # Should be JSON-serializable
        json_str = json.dumps(d)
        assert len(json_str) > 0
