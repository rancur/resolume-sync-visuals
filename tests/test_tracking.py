"""Tests for cost tracking and render registry."""
import tempfile
from pathlib import Path

import pytest

from src.tracking.costs import CostTracker, BudgetExceededError
from src.tracking.registry import RenderRegistry


class TestCostTracker:
    def _make_tracker(self):
        db = Path(tempfile.mktemp(suffix=".db"))
        return CostTracker(db_path=db)

    def test_log_call(self):
        tracker = self._make_tracker()
        cost = tracker.log_call(
            model="dall-e-3:hd:1792x1024",
            track_name="Test Track",
            phrase_idx=0,
            phrase_label="drop",
            style="cyberpunk",
            backend="openai",
        )
        assert cost == 0.08

    def test_cached_call_free(self):
        tracker = self._make_tracker()
        cost = tracker.log_call(
            model="dall-e-3:hd:1792x1024",
            track_name="Test",
            cached=True,
        )
        assert cost == 0.0

    def test_total_cost(self):
        tracker = self._make_tracker()
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="A")
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="A")
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="B", cached=True)

        assert tracker.get_total_cost() == pytest.approx(0.16)
        assert tracker.get_total_calls() == 2  # Excludes cached

    def test_cost_by_track(self):
        tracker = self._make_tracker()
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="Track A")
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="Track A")
        tracker.log_call(model="dall-e-3:standard:1792x1024", track_name="Track B")

        by_track = tracker.get_cost_by_track()
        assert len(by_track) == 2
        # Track A should be more expensive
        assert by_track[0]["track_name"] == "Track A"

    def test_budget_exceeded(self):
        tracker = CostTracker(
            db_path=Path(tempfile.mktemp(suffix=".db")),
            budget_limit=0.10,
        )
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="A")  # $0.08
        with pytest.raises(BudgetExceededError):
            tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="A")  # $0.16 > $0.10

    def test_session_summary(self):
        tracker = self._make_tracker()
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="A")
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="A", cached=True)

        summary = tracker.get_session_summary()
        assert summary["session_calls"] == 2
        assert summary["session_api_calls"] == 1
        assert summary["session_cache_hits"] == 1
        assert summary["session_cost"] == pytest.approx(0.08)

    def test_cache_hit_rate(self):
        tracker = self._make_tracker()
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="A")
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="A", cached=True)
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="A", cached=True)

        rate = tracker.get_cache_hit_rate()
        assert rate == pytest.approx(2 / 3)

    def test_export_json(self):
        tracker = self._make_tracker()
        tracker.log_call(model="dall-e-3:hd:1792x1024", track_name="A", style="cyberpunk")

        report = tracker.export_json()
        assert report["total_cost"] == pytest.approx(0.08)
        assert report["total_api_calls"] == 1
        assert len(report["by_track"]) == 1
        assert len(report["by_style"]) == 1


class TestRenderRegistry:
    def _make_registry(self):
        db = Path(tempfile.mktemp(suffix=".db"))
        return RenderRegistry(db_path=db)

    def test_hash_audio(self, tmp_path):
        # Create a test file
        test_file = tmp_path / "test.wav"
        test_file.write_bytes(b"\x00" * 10000)

        h = RenderRegistry.hash_audio(test_file)
        assert len(h) == 16
        # Same file = same hash
        assert RenderRegistry.hash_audio(test_file) == h

    def test_compute_render_hash(self):
        h1 = RenderRegistry.compute_render_hash("abc", "cyberpunk", "high", 1920, 1080, 8, 0, "openai")
        h2 = RenderRegistry.compute_render_hash("abc", "cyberpunk", "high", 1920, 1080, 8, 0, "openai")
        h3 = RenderRegistry.compute_render_hash("abc", "laser", "high", 1920, 1080, 8, 0, "openai")

        assert h1 == h2  # Same inputs = same hash
        assert h1 != h3  # Different style = different hash

    def test_render_lifecycle(self, tmp_path):
        registry = self._make_registry()

        render_hash = "test_hash_123"
        output_file = tmp_path / "output.mp4"
        output_file.write_bytes(b"\x00" * 5000)

        # Not rendered yet
        assert registry.is_rendered(render_hash) is None

        # Start render
        rid = registry.start_render(
            render_hash=render_hash, audio_hash="audio_abc",
            audio_path="/test.wav", track_name="Test",
            style="cyberpunk", quality="high",
            width=1920, height=1080, fps=30,
            loop_beats=8, backend="openai",
            phrase_idx=0, phrase_label="drop",
        )
        assert rid > 0

        # Complete render
        registry.complete_render(render_hash, str(output_file), cost_usd=0.24, api_calls=3)

        # Now it should be found
        result = registry.is_rendered(render_hash)
        assert result is not None
        assert result["output_path"] == str(output_file)
        assert result["cost_usd"] == pytest.approx(0.24)

    def test_invalidated_when_file_missing(self, tmp_path):
        registry = self._make_registry()
        render_hash = "hash_missing_file"

        registry.start_render(
            render_hash=render_hash, audio_hash="audio_abc",
            audio_path="/test.wav", track_name="Test",
            style="cyberpunk", quality="high",
            width=1920, height=1080, fps=30,
            loop_beats=8, backend="openai",
        )
        registry.complete_render(render_hash, "/nonexistent/path.mp4")

        # File doesn't exist — should return None and mark as invalidated
        assert registry.is_rendered(render_hash) is None

    def test_render_stats(self, tmp_path):
        registry = self._make_registry()
        output_file = tmp_path / "out.mp4"
        output_file.write_bytes(b"\x00" * 5000)

        for i in range(3):
            h = f"hash_{i}"
            registry.start_render(
                render_hash=h, audio_hash="audio_1",
                audio_path="/test.wav", track_name="Track",
                style="cyberpunk", quality="high",
                width=1920, height=1080, fps=30,
                loop_beats=8, backend="openai", phrase_idx=i,
            )
            if i < 2:
                registry.complete_render(h, str(output_file))
            else:
                registry.fail_render(h, "test error")

        stats = registry.get_render_stats()
        assert stats["total_renders"] == 3
        assert stats["completed"] == 2
        assert stats["failed"] == 1

    def test_invalidate_style(self, tmp_path):
        registry = self._make_registry()
        output_file = tmp_path / "out.mp4"
        output_file.write_bytes(b"\x00" * 5000)

        for i in range(3):
            h = f"style_hash_{i}"
            registry.start_render(
                render_hash=h, audio_hash="audio_1",
                audio_path="/test.wav", track_name="Track",
                style="cyberpunk", quality="high",
                width=1920, height=1080, fps=30,
                loop_beats=8, backend="openai",
            )
            registry.complete_render(h, str(output_file))

        count = registry.invalidate_style("cyberpunk")
        assert count == 3
