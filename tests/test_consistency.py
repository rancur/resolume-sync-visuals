"""Tests for visual consistency scoring across a full set."""
import pytest

from src.generator.consistency import (
    ConsistencyReport,
    TrackVisualProfile,
    compute_similarity,
    score_consistency,
)


# ── TrackVisualProfile ───────────────────────────────────────────────

class TestTrackVisualProfile:
    def test_to_dict(self):
        p = TrackVisualProfile(
            track_title="Test Track",
            avg_brightness=128.0,
            avg_saturation=100.0,
            dominant_hue=90.0,
        )
        d = p.to_dict()
        assert d["track_title"] == "Test Track"
        assert d["avg_brightness"] == 128.0


# ── Similarity ───────────────────────────────────────────────────────

class TestComputeSimilarity:
    def test_identical_profiles(self):
        a = TrackVisualProfile("A", avg_brightness=128, avg_saturation=100, dominant_hue=90)
        b = TrackVisualProfile("B", avg_brightness=128, avg_saturation=100, dominant_hue=90)
        sim = compute_similarity(a, b)
        assert sim == pytest.approx(1.0, abs=0.01)

    def test_different_profiles(self):
        a = TrackVisualProfile("A", avg_brightness=200, avg_saturation=200, dominant_hue=0)
        b = TrackVisualProfile("B", avg_brightness=50, avg_saturation=50, dominant_hue=90)
        sim = compute_similarity(a, b)
        assert sim < 0.5

    def test_range_0_to_1(self):
        a = TrackVisualProfile("A", avg_brightness=0, avg_saturation=0, dominant_hue=0)
        b = TrackVisualProfile("B", avg_brightness=255, avg_saturation=255, dominant_hue=180)
        sim = compute_similarity(a, b)
        assert 0.0 <= sim <= 1.0

    def test_symmetric(self):
        a = TrackVisualProfile("A", avg_brightness=100, avg_saturation=80, dominant_hue=60)
        b = TrackVisualProfile("B", avg_brightness=150, avg_saturation=120, dominant_hue=30)
        assert compute_similarity(a, b) == pytest.approx(compute_similarity(b, a))

    def test_hue_circularity(self):
        # Hue 0 and 180 are close on the circle (both are red-ish)
        a = TrackVisualProfile("A", avg_brightness=128, avg_saturation=100, dominant_hue=5)
        b = TrackVisualProfile("B", avg_brightness=128, avg_saturation=100, dominant_hue=175)
        sim = compute_similarity(a, b)
        # Should be higher than midpoint hue (90)
        c = TrackVisualProfile("C", avg_brightness=128, avg_saturation=100, dominant_hue=90)
        sim_far = compute_similarity(a, c)
        assert sim > sim_far


# ── Consistency scoring ──────────────────────────────────────────────

class TestScoreConsistency:
    def _make_consistent_profiles(self, n: int = 5) -> list[TrackVisualProfile]:
        """Create profiles that are visually consistent."""
        return [
            TrackVisualProfile(f"Track {i}", avg_brightness=120 + i * 2,
                             avg_saturation=100 + i, dominant_hue=60 + i)
            for i in range(n)
        ]

    def _make_inconsistent_profiles(self) -> list[TrackVisualProfile]:
        """Create profiles with one clear outlier."""
        profiles = [
            TrackVisualProfile("Track A", avg_brightness=120, avg_saturation=100, dominant_hue=60),
            TrackVisualProfile("Track B", avg_brightness=125, avg_saturation=105, dominant_hue=65),
            TrackVisualProfile("Track C", avg_brightness=118, avg_saturation=98, dominant_hue=58),
            # Outlier: completely different
            TrackVisualProfile("Outlier", avg_brightness=20, avg_saturation=10, dominant_hue=170),
        ]
        return profiles

    def test_consistent_set_high_score(self):
        profiles = self._make_consistent_profiles()
        report = score_consistency(profiles)
        assert report.score > 70

    def test_inconsistent_set_has_outliers(self):
        profiles = self._make_inconsistent_profiles()
        report = score_consistency(profiles, outlier_threshold=0.7)
        assert len(report.outliers) > 0
        outlier_titles = [o["track_title"] for o in report.outliers]
        assert "Outlier" in outlier_titles

    def test_single_track_perfect_score(self):
        profiles = [TrackVisualProfile("Solo", avg_brightness=128)]
        report = score_consistency(profiles)
        assert report.score == 100

    def test_empty_set(self):
        report = score_consistency([])
        assert report.total_tracks == 0

    def test_report_to_dict(self):
        profiles = self._make_consistent_profiles(3)
        report = score_consistency(profiles, brand="test_brand")
        d = report.to_dict()
        assert d["brand"] == "test_brand"
        assert d["total_tracks"] == 3
        assert "similarity_matrix" in d
        assert "score" in d

    def test_similarity_matrix_dimensions(self):
        profiles = self._make_consistent_profiles(4)
        report = score_consistency(profiles)
        assert len(report.similarity_matrix) == 4
        assert all(len(row) == 4 for row in report.similarity_matrix)

    def test_suggestions_for_outliers(self):
        profiles = self._make_inconsistent_profiles()
        report = score_consistency(profiles, outlier_threshold=0.7)
        if report.outliers:
            assert len(report.suggestions) > 0

    def test_avg_similarity_in_range(self):
        profiles = self._make_consistent_profiles()
        report = score_consistency(profiles)
        assert 0.0 <= report.avg_similarity <= 1.0
