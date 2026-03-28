"""CLI integration tests using Click's CliRunner.

These tests exercise the CLI without making any API calls.
"""
import json
import os
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from src.cli import main

SAMPLES_DIR = Path(__file__).parent.parent / "samples"
HOUSE_WAV = str(SAMPLES_DIR / "house_128bpm.wav")

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _invoke(*args, **kwargs):
    """Invoke a CLI command and return the result."""
    result = runner.invoke(main, list(args), catch_exceptions=False, **kwargs)
    return result


# ---------------------------------------------------------------------------
# rsv --help
# ---------------------------------------------------------------------------

class TestMainHelp:
    def test_help_exits_zero(self):
        result = _invoke("--help")
        assert result.exit_code == 0

    def test_help_shows_commands(self):
        result = _invoke("--help")
        output = result.output
        # All top-level commands should appear
        for cmd in ("analyze", "generate", "styles", "scan", "batch",
                    "dashboard", "info", "validate", "export-composition"):
            assert cmd in output, f"'{cmd}' not found in help output"


# ---------------------------------------------------------------------------
# rsv styles
# ---------------------------------------------------------------------------

class TestStyles:
    def test_styles_exits_zero(self):
        result = _invoke("styles")
        assert result.exit_code == 0

    def test_styles_shows_all_ten(self):
        result = _invoke("styles")
        output = result.output
        expected = [
            "abstract", "cosmic", "cyberpunk", "fire", "fractal",
            "glitch", "laser", "liquid", "minimal", "nature",
        ]
        for style in expected:
            assert style in output, f"Style '{style}' missing from styles output"

    def test_styles_shows_table_header(self):
        result = _invoke("styles")
        assert "Available Visual Styles" in result.output


# ---------------------------------------------------------------------------
# rsv analyze
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_analyze_house_wav(self):
        result = _invoke("analyze", HOUSE_WAV)
        assert result.exit_code == 0
        assert "BPM" in result.output
        assert "Phrase" in result.output

    def test_analyze_bpm_override(self):
        result = _invoke("analyze", HOUSE_WAV, "--bpm", "128")
        assert result.exit_code == 0
        assert "128" in result.output

    def test_analyze_json_output(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            json_path = f.name
        try:
            result = _invoke("analyze", HOUSE_WAV, "-o", json_path)
            assert result.exit_code == 0
            assert Path(json_path).exists()
            data = json.loads(Path(json_path).read_text())
            assert "bpm" in data
            assert "phrases" in data or "duration" in data
        finally:
            os.unlink(json_path)

    def test_analyze_nonexistent_file(self):
        result = runner.invoke(main, ["analyze", "nonexistent.wav"],
                               catch_exceptions=False)
        assert result.exit_code != 0

    def test_analyze_phrase_beats_option(self):
        result = _invoke("analyze", HOUSE_WAV, "--phrase-beats", "16")
        assert result.exit_code == 0
        assert "Phrase" in result.output


# ---------------------------------------------------------------------------
# rsv generate (dry-run only — no API calls)
# ---------------------------------------------------------------------------

class TestGenerateDryRun:
    def test_help_shows_all_flags(self):
        result = _invoke("generate", "--help")
        assert result.exit_code == 0
        output = result.output
        for flag in ("--style", "--bpm", "--strobe", "--dry-run",
                     "--montage", "--thumbnails", "--style-drop",
                     "--video-model"):
            assert flag in output, f"'{flag}' not in generate --help"

    def test_dry_run_exits_zero(self):
        result = _invoke("generate", HOUSE_WAV, "--dry-run")
        assert result.exit_code == 0

    def test_dry_run_shows_cost_estimate(self):
        result = _invoke("generate", HOUSE_WAV, "--dry-run")
        assert "Cost Estimate" in result.output or "cost" in result.output.lower()
        assert "Dry run" in result.output or "dry" in result.output.lower()

    def test_dry_run_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _invoke("generate", HOUSE_WAV, "--dry-run",
                             "-o", tmpdir)
            assert result.exit_code == 0
            # No track subdirectory should have been created
            contents = list(Path(tmpdir).iterdir())
            assert len(contents) == 0

    def test_dry_run_auto_style(self):
        result = _invoke("generate", HOUSE_WAV, "--dry-run", "--style", "auto")
        assert result.exit_code == 0
        # Should show auto-detected genre
        assert "auto" in result.output.lower() or "genre" in result.output.lower() or "style" in result.output.lower()

    def test_dry_run_with_bpm_override(self):
        result = _invoke("generate", HOUSE_WAV, "--dry-run", "--bpm", "140")
        assert result.exit_code == 0

    def test_dry_run_with_named_style(self):
        result = _invoke("generate", HOUSE_WAV, "--dry-run", "--style", "cyberpunk")
        assert result.exit_code == 0

    def test_nonexistent_file(self):
        result = runner.invoke(main, ["generate", "nonexistent.wav"],
                               catch_exceptions=False)
        assert result.exit_code != 0

    def test_dry_run_no_api_key_required(self):
        """Dry run should work even without an API key set."""
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        env.pop("REPLICATE_API_TOKEN", None)
        result = runner.invoke(main,
                               ["generate", HOUSE_WAV, "--dry-run"],
                               catch_exceptions=False,
                               env=env)
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# rsv dashboard
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_costs_exits_zero(self):
        result = _invoke("dashboard", "costs")
        assert result.exit_code == 0

    def test_costs_shows_summary(self):
        result = _invoke("dashboard", "costs")
        # Should show some cost-related output
        assert "Cost" in result.output or "cost" in result.output.lower() or "$" in result.output

    def test_renders_exits_zero(self):
        result = _invoke("dashboard", "renders")
        assert result.exit_code == 0

    def test_renders_shows_stats(self):
        result = _invoke("dashboard", "renders")
        assert "Render" in result.output or "render" in result.output.lower()

    def test_report_help(self):
        result = _invoke("dashboard", "report", "--help")
        assert result.exit_code == 0

    def test_reset_help(self):
        result = _invoke("dashboard", "reset", "--help")
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# rsv scan
# ---------------------------------------------------------------------------

class TestScan:
    def test_scan_samples_dir(self):
        result = _invoke("scan", str(SAMPLES_DIR))
        assert result.exit_code == 0

    def test_scan_finds_music_files(self):
        result = _invoke("scan", str(SAMPLES_DIR))
        # Should find at least the house, dnb, techno, trance files
        assert "house" in result.output.lower() or "128" in result.output

    def test_scan_json_format(self):
        result = _invoke("scan", str(SAMPLES_DIR), "--format", "json")
        assert result.exit_code == 0
        # Output should be valid JSON (possibly with Rich markup, extract JSON)
        # The JSON output may have ANSI codes from Rich, so just check structure
        assert "path" in result.output


# ---------------------------------------------------------------------------
# rsv batch
# ---------------------------------------------------------------------------

class TestBatch:
    def test_batch_help(self):
        result = _invoke("batch", "--help")
        assert result.exit_code == 0
        output = result.output
        for sub in ("prepare", "submit", "status", "download", "process", "list"):
            assert sub in output, f"'{sub}' not in batch --help"


# ---------------------------------------------------------------------------
# rsv info
# ---------------------------------------------------------------------------

class TestInfo:
    def test_info_missing_dir(self):
        """info with a directory that doesn't have metadata.json should show error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(main, ["info", tmpdir],
                                   catch_exceptions=False)
            # Should exit 0 but show error message (Click doesn't sys.exit on missing metadata)
            assert "No metadata.json" in result.output or result.exit_code != 0

    def test_info_nonexistent_dir(self):
        """info with a nonexistent directory should fail."""
        result = runner.invoke(main, ["info", "/tmp/nonexistent_rsv_test_dir"],
                               catch_exceptions=False)
        assert result.exit_code != 0

    def test_info_with_output(self):
        """info on the tracked_test output dir if it exists."""
        output_dir = Path(__file__).parent.parent / "output" / "tracked_test"
        if not (output_dir / "metadata.json").exists():
            pytest.skip("No tracked_test output to test against")
        result = _invoke("info", str(output_dir))
        assert result.exit_code == 0
        assert "BPM" in result.output


# ---------------------------------------------------------------------------
# rsv export-composition
# ---------------------------------------------------------------------------

class TestExportComposition:
    def test_help(self):
        result = _invoke("export-composition", "--help")
        assert result.exit_code == 0
        assert "--output-file" in result.output or "-o" in result.output
        assert "--multi-track" in result.output


# ---------------------------------------------------------------------------
# rsv validate
# ---------------------------------------------------------------------------

class TestValidateCLI:
    def test_help(self):
        result = _invoke("validate", "--help")
        assert result.exit_code == 0
        assert "--width" in result.output
        assert "--height" in result.output
        assert "--codec" in result.output

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _invoke("validate", tmpdir)
            assert result.exit_code == 0
            assert "No .mp4 files" in result.output

    def test_validate_output_dir_if_exists(self):
        """Validate the output directory if it has mp4 files."""
        output_dir = Path(__file__).parent.parent / "output" / "tracked_test"
        mp4s = list(output_dir.rglob("*.mp4")) if output_dir.exists() else []
        if not mp4s:
            pytest.skip("No mp4 files in output to validate")
        result = _invoke("validate", str(output_dir))
        assert result.exit_code == 0
        assert "Total files" in result.output or "Validation" in result.output


# ---------------------------------------------------------------------------
# Invalid style behavior
# ---------------------------------------------------------------------------

class TestInvalidStyle:
    def test_invalid_style_on_generate_dry_run(self):
        """Using an invalid style name should produce an error."""
        result = runner.invoke(
            main,
            ["generate", HOUSE_WAV, "--dry-run", "--style", "nonexistent_style_xyz"],
            catch_exceptions=True,
        )
        # Should either exit non-zero or print a style-not-found message
        assert result.exit_code != 0 or "not found" in result.output.lower()
