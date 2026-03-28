"""Tests for OpenAI Batch API support."""
import json
import tempfile
from pathlib import Path

import pytest

from src.generator.batch import (
    prepare_batch,
    parse_custom_id,
    estimate_batch_cost,
    _n_keyframes,
    _dalle_quality,
)
from src.generator.engine import GenerationConfig
from src.tracking.costs import CostTracker, PRICING


def _make_analysis(title="Test Track", n_phrases=3, energy_levels=None):
    """Create a mock analysis dict."""
    if energy_levels is None:
        energy_levels = [0.3, 0.6, 0.9]
    phrases = []
    labels = ["intro", "buildup", "drop", "breakdown", "outro"]
    for i, energy in enumerate(energy_levels[:n_phrases]):
        label = labels[i % len(labels)]
        phrases.append({
            "label": label,
            "start": i * 8.0,
            "end": (i + 1) * 8.0,
            "beats": 16,
            "energy": energy,
        })
    return {
        "title": title,
        "bpm": 128.0,
        "duration": n_phrases * 8.0,
        "phrases": phrases,
    }


def _make_config(**kwargs):
    """Create a GenerationConfig with sensible defaults."""
    defaults = {
        "style_name": "abstract",
        "style_config": {
            "name": "abstract",
            "prompts": {"base": "abstract visual art"},
            "colors": {"primary": "#FF00FF", "secondary": "#00FFFF"},
        },
        "quality": "high",
        "output_dir": "output/test/raw",
        "cache_dir": "output/test/.cache",
        "backend": "openai",
    }
    defaults.update(kwargs)
    return GenerationConfig(**defaults)


class TestParseCustomId:
    def test_standard_format(self):
        result = parse_custom_id("track_0_phrase_2_kf_1")
        assert result == {"track_idx": 0, "phrase_idx": 2, "kf_idx": 1}

    def test_large_indices(self):
        result = parse_custom_id("track_15_phrase_42_kf_3")
        assert result == {"track_idx": 15, "phrase_idx": 42, "kf_idx": 3}

    def test_zero_indices(self):
        result = parse_custom_id("track_0_phrase_0_kf_0")
        assert result == {"track_idx": 0, "phrase_idx": 0, "kf_idx": 0}


class TestNKeyframes:
    def test_low_energy(self):
        assert _n_keyframes(0.2, "high") == 2

    def test_mid_energy(self):
        assert _n_keyframes(0.5, "high") == 3

    def test_high_energy(self):
        assert _n_keyframes(0.8, "high") == 4

    def test_draft_caps_at_2(self):
        assert _n_keyframes(0.9, "draft") == 2


class TestDalleQuality:
    def test_high_maps_to_hd(self):
        assert _dalle_quality("high") == "hd"

    def test_standard_maps_to_standard(self):
        assert _dalle_quality("standard") == "standard"

    def test_draft_maps_to_standard(self):
        assert _dalle_quality("draft") == "standard"


class TestPrepareBatch:
    def test_creates_jsonl_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analysis = _make_analysis(n_phrases=2, energy_levels=[0.3, 0.8])
            config = _make_config(output_dir=f"{tmpdir}/raw")
            jsonl_path = prepare_batch([analysis], [config], Path(tmpdir))

            assert jsonl_path.exists()
            assert jsonl_path.name == "batch_requests.jsonl"

    def test_jsonl_line_count(self):
        """Each phrase generates keyframes based on energy. low=2, high=4."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # energy 0.3 -> 2 kf, energy 0.8 -> 4 kf = 6 total
            analysis = _make_analysis(n_phrases=2, energy_levels=[0.3, 0.8])
            config = _make_config(output_dir=f"{tmpdir}/raw")
            jsonl_path = prepare_batch([analysis], [config], Path(tmpdir))

            with open(jsonl_path) as f:
                lines = [l for l in f if l.strip()]
            assert len(lines) == 6

    def test_jsonl_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analysis = _make_analysis(n_phrases=1, energy_levels=[0.5])
            config = _make_config(output_dir=f"{tmpdir}/raw")
            jsonl_path = prepare_batch([analysis], [config], Path(tmpdir))

            with open(jsonl_path) as f:
                first_line = json.loads(f.readline())

            assert "custom_id" in first_line
            assert first_line["method"] == "POST"
            assert first_line["url"] == "/v1/images/generations"
            assert first_line["body"]["model"] == "dall-e-3"
            assert first_line["body"]["size"] == "1792x1024"
            assert first_line["body"]["n"] == 1

    def test_custom_id_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analysis = _make_analysis(n_phrases=1, energy_levels=[0.3])
            config = _make_config(output_dir=f"{tmpdir}/raw")
            jsonl_path = prepare_batch([analysis], [config], Path(tmpdir))

            with open(jsonl_path) as f:
                lines = [json.loads(l) for l in f if l.strip()]

            assert lines[0]["custom_id"] == "track_0_phrase_0_kf_0"
            assert lines[1]["custom_id"] == "track_0_phrase_0_kf_1"

    def test_quality_mapping_hd(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analysis = _make_analysis(n_phrases=1, energy_levels=[0.3])
            config = _make_config(quality="high", output_dir=f"{tmpdir}/raw")
            jsonl_path = prepare_batch([analysis], [config], Path(tmpdir))

            with open(jsonl_path) as f:
                first = json.loads(f.readline())
            assert first["body"]["quality"] == "hd"

    def test_quality_mapping_standard(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analysis = _make_analysis(n_phrases=1, energy_levels=[0.3])
            config = _make_config(quality="standard", output_dir=f"{tmpdir}/raw")
            jsonl_path = prepare_batch([analysis], [config], Path(tmpdir))

            with open(jsonl_path) as f:
                first = json.loads(f.readline())
            assert first["body"]["quality"] == "standard"

    def test_multiple_tracks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            a1 = _make_analysis(title="Track A", n_phrases=1, energy_levels=[0.3])
            a2 = _make_analysis(title="Track B", n_phrases=1, energy_levels=[0.3])
            c1 = _make_config(output_dir=f"{tmpdir}/a/raw")
            c2 = _make_config(output_dir=f"{tmpdir}/b/raw")

            jsonl_path = prepare_batch([a1, a2], [c1, c2], Path(tmpdir))

            with open(jsonl_path) as f:
                lines = [json.loads(l) for l in f if l.strip()]

            # 2 keyframes per phrase (energy 0.3), 1 phrase each = 4 total
            assert len(lines) == 4
            assert lines[0]["custom_id"].startswith("track_0")
            assert lines[2]["custom_id"].startswith("track_1")

    def test_draft_quality_limits_keyframes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # High energy would give 4 kf normally, but draft caps at 2
            analysis = _make_analysis(n_phrases=1, energy_levels=[0.9])
            config = _make_config(quality="draft", output_dir=f"{tmpdir}/raw")
            jsonl_path = prepare_batch([analysis], [config], Path(tmpdir))

            with open(jsonl_path) as f:
                lines = [l for l in f if l.strip()]
            assert len(lines) == 2

    def test_keyframe_variation_prompts(self):
        """Keyframes beyond the first should have variation suffixes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analysis = _make_analysis(n_phrases=1, energy_levels=[0.5])
            config = _make_config(output_dir=f"{tmpdir}/raw")
            jsonl_path = prepare_batch([analysis], [config], Path(tmpdir))

            with open(jsonl_path) as f:
                lines = [json.loads(l) for l in f if l.strip()]

            # First keyframe: base prompt only (no variation suffix)
            # Second+ keyframes: should have a variation suffix
            first_prompt = lines[0]["body"]["prompt"]
            second_prompt = lines[1]["body"]["prompt"]
            variations = ["slightly different angle", "subtle color shift",
                          "camera slowly moving", "gentle perspective change"]
            assert not any(v in first_prompt for v in variations)
            assert any(v in second_prompt for v in variations)


class TestEstimateBatchCost:
    def test_basic_estimate(self):
        analysis = _make_analysis(n_phrases=2, energy_levels=[0.3, 0.8])
        config = _make_config(quality="high")
        estimate = estimate_batch_cost([analysis], [config])

        # 2 + 4 = 6 requests
        assert estimate["total_requests"] == 6
        # HD sync: 6 * $0.08 = $0.48
        assert estimate["sync_cost"] == pytest.approx(0.48)
        # Batch: 6 * $0.04 = $0.24
        assert estimate["batch_cost"] == pytest.approx(0.24)
        # Savings: $0.24
        assert estimate["savings"] == pytest.approx(0.24)

    def test_standard_quality_pricing(self):
        analysis = _make_analysis(n_phrases=1, energy_levels=[0.3])
        config = _make_config(quality="standard")
        estimate = estimate_batch_cost([analysis], [config])

        # 2 requests, standard sync: $0.04 each, batch: $0.02 each
        assert estimate["total_requests"] == 2
        assert estimate["sync_cost"] == pytest.approx(0.08)
        assert estimate["batch_cost"] == pytest.approx(0.04)

    def test_per_track_breakdown(self):
        a1 = _make_analysis(title="Track A", n_phrases=1, energy_levels=[0.3])
        a2 = _make_analysis(title="Track B", n_phrases=1, energy_levels=[0.3])
        c1 = _make_config()
        c2 = _make_config()
        estimate = estimate_batch_cost([a1, a2], [c1, c2])

        assert len(estimate["per_track"]) == 2
        assert estimate["per_track"][0]["track"] == "Track A"
        assert estimate["per_track"][1]["track"] == "Track B"

    def test_savings_is_50_percent(self):
        analysis = _make_analysis(n_phrases=5, energy_levels=[0.5] * 5)
        config = _make_config(quality="high")
        estimate = estimate_batch_cost([analysis], [config])

        assert estimate["savings"] == pytest.approx(estimate["sync_cost"] / 2)


class TestCostTrackingBatchPrices:
    def _make_tracker(self):
        db = Path(tempfile.mktemp(suffix=".db"))
        return CostTracker(db_path=db)

    def test_batch_pricing_exists(self):
        """Verify batch pricing keys exist in PRICING dict."""
        assert "dall-e-3:hd:1792x1024:batch" in PRICING
        assert "dall-e-3:standard:1792x1024:batch" in PRICING

    def test_batch_hd_is_half_sync(self):
        sync_price = PRICING["dall-e-3:hd:1792x1024"]
        batch_price = PRICING["dall-e-3:hd:1792x1024:batch"]
        assert batch_price == pytest.approx(sync_price / 2)

    def test_batch_standard_is_half_sync(self):
        sync_price = PRICING["dall-e-3:standard:1792x1024"]
        batch_price = PRICING["dall-e-3:standard:1792x1024:batch"]
        assert batch_price == pytest.approx(sync_price / 2)

    def test_log_batch_call(self):
        tracker = self._make_tracker()
        cost = tracker.log_call(
            model="dall-e-3:hd:1792x1024:batch",
            track_name="Test Track",
            phrase_idx=0,
            phrase_label="drop",
            style="cyberpunk",
            backend="openai:batch",
        )
        assert cost == pytest.approx(0.04)

    def test_batch_vs_sync_cost_comparison(self):
        tracker = self._make_tracker()

        sync_cost = tracker.log_call(
            model="dall-e-3:hd:1792x1024",
            track_name="Test",
            backend="openai",
        )
        batch_cost = tracker.log_call(
            model="dall-e-3:hd:1792x1024:batch",
            track_name="Test",
            backend="openai:batch",
        )
        assert batch_cost == pytest.approx(sync_cost / 2)


class TestBatchResultProcessing:
    """Test result grouping and custom_id parsing for process_batch_results."""

    def test_results_group_by_track_and_phrase(self):
        """Verify parse_custom_id correctly groups results."""
        results = [
            {"custom_id": "track_0_phrase_0_kf_0", "image_path": "/tmp/a.png", "error": None},
            {"custom_id": "track_0_phrase_0_kf_1", "image_path": "/tmp/b.png", "error": None},
            {"custom_id": "track_0_phrase_1_kf_0", "image_path": "/tmp/c.png", "error": None},
            {"custom_id": "track_1_phrase_0_kf_0", "image_path": "/tmp/d.png", "error": None},
        ]

        for r in results:
            r.update(parse_custom_id(r["custom_id"]))

        by_track = {}
        for r in results:
            by_track.setdefault(r["track_idx"], []).append(r)

        assert len(by_track) == 2
        assert len(by_track[0]) == 3
        assert len(by_track[1]) == 1

    def test_error_results_have_no_image_path(self):
        results = [
            {"custom_id": "track_0_phrase_0_kf_0", "image_path": None, "error": "Rate limited"},
        ]
        for r in results:
            r.update(parse_custom_id(r["custom_id"]))

        assert results[0]["image_path"] is None
        assert results[0]["error"] == "Rate limited"
        assert results[0]["track_idx"] == 0
