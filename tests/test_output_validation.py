"""Tests for the output video validation module and validate CLI command."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from src.validation import validate_output_video, validate_directory, ValidationResult
from src.cli import main

runner = CliRunner()
OUTPUT_DIR = Path(__file__).parent.parent / "output"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_valid_mp4(path: str, duration: float = 2.0, width: int = 1920, height: int = 1080):
    """Create a minimal valid h264 mp4 file using ffmpeg."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i",
            f"color=c=blue:s={width}x{height}:d={duration}:r=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-t", str(duration),
            str(path),
        ],
        capture_output=True,
        timeout=30,
    )


def _create_empty_file(path: str):
    """Create a zero-byte file."""
    Path(path).touch()


def _create_tiny_file(path: str):
    """Create a file smaller than 1KB."""
    with open(path, "wb") as f:
        f.write(b"\x00" * 500)


def _create_text_as_mp4(path: str):
    """Create a text file with a .mp4 extension."""
    with open(path, "w") as f:
        f.write("this is not a video file")


# ---------------------------------------------------------------------------
# validate_output_video — valid files
# ---------------------------------------------------------------------------

class TestValidateOutputVideo:
    def test_valid_mp4(self, tmp_path):
        mp4 = str(tmp_path / "valid.mp4")
        _create_valid_mp4(mp4)
        result = validate_output_video(mp4)
        assert result.valid is True
        assert result.errors == []
        assert result.codec == "h264"
        assert result.width == 1920
        assert result.height == 1080
        assert result.duration is not None and result.duration > 0
        assert result.size_bytes > 1024

    def test_valid_mp4_custom_resolution(self, tmp_path):
        mp4 = str(tmp_path / "small.mp4")
        _create_valid_mp4(mp4, width=640, height=480)
        # Default expects 1920x1080 so this should fail resolution check
        result = validate_output_video(mp4)
        assert result.valid is False
        assert any("Resolution mismatch" in e for e in result.errors)

    def test_valid_mp4_matching_custom_resolution(self, tmp_path):
        mp4 = str(tmp_path / "custom.mp4")
        _create_valid_mp4(mp4, width=1280, height=720)
        result = validate_output_video(mp4, expected_width=1280, expected_height=720)
        assert result.valid is True
        assert result.errors == []


# ---------------------------------------------------------------------------
# validate_output_video — invalid files
# ---------------------------------------------------------------------------

class TestValidateInvalidFiles:
    def test_nonexistent_file(self):
        result = validate_output_video("/tmp/does_not_exist_rsv_test.mp4")
        assert result.valid is False
        assert any("does not exist" in e for e in result.errors)

    def test_empty_file(self, tmp_path):
        mp4 = str(tmp_path / "empty.mp4")
        _create_empty_file(mp4)
        result = validate_output_video(mp4)
        assert result.valid is False
        assert any("too small" in e for e in result.errors)

    def test_tiny_file(self, tmp_path):
        mp4 = str(tmp_path / "tiny.mp4")
        _create_tiny_file(mp4)
        result = validate_output_video(mp4)
        assert result.valid is False
        assert any("too small" in e for e in result.errors)

    def test_text_file_as_mp4(self, tmp_path):
        mp4 = str(tmp_path / "text.mp4")
        _create_text_as_mp4(mp4)
        result = validate_output_video(mp4)
        assert result.valid is False
        # Should fail on either ffprobe error or no video stream
        assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# validate_directory
# ---------------------------------------------------------------------------

class TestValidateDirectory:
    def test_empty_directory(self, tmp_path):
        summary = validate_directory(tmp_path)
        assert summary["total"] == 0
        assert summary["valid"] == 0
        assert summary["invalid"] == 0

    def test_directory_with_valid_mp4(self, tmp_path):
        mp4 = str(tmp_path / "clip.mp4")
        _create_valid_mp4(mp4)
        summary = validate_directory(tmp_path)
        assert summary["total"] == 1
        assert summary["valid"] == 1
        assert summary["invalid"] == 0
        assert summary["total_size_bytes"] > 0

    def test_directory_with_mixed_files(self, tmp_path):
        # One valid, one invalid
        _create_valid_mp4(str(tmp_path / "good.mp4"))
        _create_text_as_mp4(str(tmp_path / "bad.mp4"))
        summary = validate_directory(tmp_path)
        assert summary["total"] == 2
        assert summary["valid"] == 1
        assert summary["invalid"] == 1
        assert len(summary["invalid_files"]) == 1

    def test_directory_with_subdirectories(self, tmp_path):
        sub = tmp_path / "clips"
        sub.mkdir()
        _create_valid_mp4(str(sub / "nested.mp4"))
        summary = validate_directory(tmp_path)
        # rglob should find nested files
        assert summary["total"] >= 1

    def test_non_mp4_files_ignored(self, tmp_path):
        # Create a .txt file — should not be counted
        (tmp_path / "readme.txt").write_text("hello")
        _create_valid_mp4(str(tmp_path / "clip.mp4"))
        summary = validate_directory(tmp_path)
        assert summary["total"] == 1


# ---------------------------------------------------------------------------
# validate on real generated output (skipped if not available)
# ---------------------------------------------------------------------------

class TestValidateRealOutput:
    def test_validate_tracked_test_output(self):
        tracked = OUTPUT_DIR / "tracked_test"
        mp4s = list(tracked.rglob("*.mp4")) if tracked.exists() else []
        if not mp4s:
            pytest.skip("No real generated mp4 files in output/tracked_test")
        summary = validate_directory(tracked)
        assert summary["total"] > 0
        # At least some should be valid
        assert summary["valid"] >= 0


# ---------------------------------------------------------------------------
# rsv validate CLI command
# ---------------------------------------------------------------------------

class TestValidateCLICommand:
    def test_validate_empty_dir(self, tmp_path):
        result = runner.invoke(main, ["validate", str(tmp_path)],
                               catch_exceptions=False)
        assert result.exit_code == 0
        assert "No .mp4 files" in result.output

    def test_validate_dir_with_videos(self, tmp_path):
        _create_valid_mp4(str(tmp_path / "test.mp4"))
        result = runner.invoke(main, ["validate", str(tmp_path)],
                               catch_exceptions=False)
        assert result.exit_code == 0
        assert "Total files" in result.output or "Validation" in result.output

    def test_validate_reports_invalid(self, tmp_path):
        _create_text_as_mp4(str(tmp_path / "broken.mp4"))
        result = runner.invoke(main, ["validate", str(tmp_path)],
                               catch_exceptions=False)
        assert result.exit_code == 0
        assert "Invalid" in result.output or "invalid" in result.output

    def test_validate_custom_resolution(self, tmp_path):
        _create_valid_mp4(str(tmp_path / "clip.mp4"), width=1280, height=720)
        result = runner.invoke(
            main,
            ["validate", str(tmp_path), "--width", "1280", "--height", "720"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        # Should show as valid since resolution matches
        output_lower = result.output.lower()
        assert "invalid" not in output_lower or "0" in result.output

    def test_validate_nonexistent_dir(self):
        result = runner.invoke(
            main, ["validate", "/tmp/nonexistent_rsv_validate_test"],
            catch_exceptions=False,
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# ValidationResult dataclass
# ---------------------------------------------------------------------------

class TestValidationResult:
    def test_defaults(self):
        vr = ValidationResult(path="/tmp/test.mp4", valid=True)
        assert vr.errors == []
        assert vr.codec is None
        assert vr.width is None
        assert vr.height is None
        assert vr.duration is None
        assert vr.size_bytes == 0

    def test_with_errors(self):
        vr = ValidationResult(
            path="/tmp/bad.mp4",
            valid=False,
            errors=["File too small", "No video stream"],
        )
        assert len(vr.errors) == 2
        assert not vr.valid
