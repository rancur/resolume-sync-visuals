"""Tests for phrase-aligned segment planning (issue #69).

Verifies that video segments align to phrase boundaries instead of a fixed
10-second grid, that long phrases split at beat-quantized points, and that
the label assignment bug (single-phrase tracks getting 'outro') is fixed.
"""
import pytest

from src.generator.video_pipeline import _plan_segments
from src.analyzer.audio import _label_phrases, Phrase


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def edm_analysis():
    """Typical EDM track analysis with varied phrase durations."""
    return {
        "file_path": "/tmp/house_128bpm.wav",
        "title": "House Track",
        "duration": 210.0,
        "bpm": 128.0,
        "time_signature": 4,
        "mood": {"mood_descriptor": "euphoric energy", "quadrant": "euphoric"},
        "phrases": [
            {"start": 0.0, "end": 15.0, "beats": 32, "energy": 0.2,
             "spectral_centroid": 1500.0, "label": "intro"},
            {"start": 15.0, "end": 30.0, "beats": 32, "energy": 0.5,
             "spectral_centroid": 2500.0, "label": "buildup"},
            {"start": 30.0, "end": 75.0, "beats": 96, "energy": 0.9,
             "spectral_centroid": 5000.0, "label": "drop"},
            {"start": 75.0, "end": 105.0, "beats": 64, "energy": 0.3,
             "spectral_centroid": 2000.0, "label": "breakdown"},
            {"start": 105.0, "end": 120.0, "beats": 32, "energy": 0.6,
             "spectral_centroid": 3000.0, "label": "buildup"},
            {"start": 120.0, "end": 165.0, "beats": 96, "energy": 0.95,
             "spectral_centroid": 5200.0, "label": "drop"},
            {"start": 165.0, "end": 210.0, "beats": 96, "energy": 0.15,
             "spectral_centroid": 1200.0, "label": "outro"},
        ],
    }


@pytest.fixture
def short_phrases_analysis():
    """Track where all phrases fit within max_segment_duration."""
    return {
        "file_path": "/tmp/short_phrases.wav",
        "title": "Short Phrases",
        "duration": 40.0,
        "bpm": 140.0,
        "time_signature": 4,
        "mood": {"mood_descriptor": "dark", "quadrant": "dark"},
        "phrases": [
            {"start": 0.0, "end": 8.0, "beats": 16, "energy": 0.3,
             "spectral_centroid": 2000.0, "label": "intro"},
            {"start": 8.0, "end": 16.0, "beats": 16, "energy": 0.6,
             "spectral_centroid": 3000.0, "label": "buildup"},
            {"start": 16.0, "end": 32.0, "beats": 32, "energy": 0.9,
             "spectral_centroid": 5000.0, "label": "drop"},
            {"start": 32.0, "end": 40.0, "beats": 16, "energy": 0.2,
             "spectral_centroid": 1500.0, "label": "outro"},
        ],
    }


# ---------------------------------------------------------------------------
# Test: Phrase boundaries ARE segment boundaries
# ---------------------------------------------------------------------------

class TestPhraseAlignment:
    """Verify segments align to phrase boundaries."""

    def test_short_phrases_become_exact_segments(self, short_phrases_analysis):
        """When phrases fit in max_segment_duration, each phrase = one segment."""
        segments = _plan_segments(short_phrases_analysis, max_segment_duration=32)
        # 4 phrases, all <= 32s => 4 segments
        assert len(segments) == 4
        assert segments[0]["start"] == 0.0
        assert segments[0]["end"] == 8.0
        assert segments[1]["start"] == 8.0
        assert segments[1]["end"] == 16.0
        assert segments[2]["start"] == 16.0
        assert segments[2]["end"] == 32.0
        assert segments[3]["start"] == 32.0
        assert segments[3]["end"] == 40.0

    def test_phrase_boundary_is_always_segment_boundary(self, edm_analysis):
        """Every phrase start/end must appear as a segment start/end."""
        segments = _plan_segments(edm_analysis, max_segment_duration=10)
        seg_starts = {s["start"] for s in segments}
        seg_ends = {s["end"] for s in segments}

        for phrase in edm_analysis["phrases"]:
            assert phrase["start"] in seg_starts, (
                f"Phrase start {phrase['start']} not a segment boundary"
            )
            # Phrase end should be a segment end (possibly with tiny float tolerance)
            assert any(
                abs(phrase["end"] - e) < 0.01 for e in seg_ends
            ), f"Phrase end {phrase['end']} not a segment boundary"

    def test_no_segment_spans_phrase_boundary(self, edm_analysis):
        """No single segment should cross a phrase boundary."""
        phrase_boundaries = set()
        for p in edm_analysis["phrases"]:
            phrase_boundaries.add(round(p["start"], 4))
            phrase_boundaries.add(round(p["end"], 4))

        segments = _plan_segments(edm_analysis, max_segment_duration=10)
        for seg in segments:
            # Check no phrase boundary lies strictly inside this segment
            for b in phrase_boundaries:
                if seg["start"] < b < seg["end"]:
                    # This boundary should only exist if it's the seg boundary
                    assert round(seg["start"], 4) == b or round(seg["end"], 4) == b, (
                        f"Segment {seg['start']:.2f}-{seg['end']:.2f} crosses "
                        f"phrase boundary at {b:.2f}"
                    )

    def test_no_fixed_10s_grid(self, edm_analysis):
        """Segments should NOT all start at multiples of 10s."""
        segments = _plan_segments(edm_analysis, max_segment_duration=10)
        starts = [s["start"] for s in segments]
        # If we had a fixed 10s grid, all starts would be multiples of 10
        multiples_of_10 = [s for s in starts if s % 10.0 == 0.0]
        # With phrase-aligned segments, not all starts are multiples of 10
        # (unless the phrases happen to align, which is unlikely with 128 BPM)
        # At minimum, the 15.0 phrase boundary must appear
        assert 15.0 in starts


# ---------------------------------------------------------------------------
# Test: Beat-quantized splitting of long phrases
# ---------------------------------------------------------------------------

class TestBeatQuantizedSplitting:
    """Verify long phrases split at beat-quantized points."""

    def test_long_phrase_splits_at_beat_boundaries(self, edm_analysis):
        """A 45s phrase at 128 BPM should split at beat-aligned points."""
        segments = _plan_segments(edm_analysis, max_segment_duration=10)
        bpm = 128.0
        beat_dur = 60.0 / bpm  # 0.46875s

        # Find segments from the first drop (30.0-75.0, 45s)
        drop_segments = [s for s in segments if s["start"] >= 30.0 and s["end"] <= 75.0]
        assert len(drop_segments) > 1, "45s drop should be split into multiple segments"

        # Each split point should be on a beat boundary relative to phrase start
        for seg in drop_segments:
            offset_from_phrase = seg["start"] - 30.0
            if offset_from_phrase == 0:
                continue  # First segment starts at phrase start
            beats = offset_from_phrase / beat_dur
            assert abs(beats - round(beats)) < 0.01, (
                f"Segment start {seg['start']:.4f} is not beat-aligned "
                f"({beats:.2f} beats from phrase start)"
            )

    def test_sub_index_increments_within_phrase(self, edm_analysis):
        """sub_index should increment for each split within a long phrase."""
        segments = _plan_segments(edm_analysis, max_segment_duration=10)

        # Find segments from the first drop (30.0-75.0)
        drop_segments = [s for s in segments if s["start"] >= 30.0 and s["end"] <= 75.01]
        assert len(drop_segments) > 1

        sub_indices = [s["sub_index"] for s in drop_segments]
        assert sub_indices[0] == 0
        for i in range(1, len(sub_indices)):
            assert sub_indices[i] == sub_indices[i - 1] + 1, (
                f"sub_index not sequential: {sub_indices}"
            )

    def test_short_phrase_gets_sub_index_zero(self, short_phrases_analysis):
        """A phrase that fits in one segment should have sub_index=0."""
        segments = _plan_segments(short_phrases_analysis, max_segment_duration=32)
        for seg in segments:
            assert seg["sub_index"] == 0

    def test_split_duration_uses_max_segment(self):
        """Split interval should use max_segment_duration directly (no sub-chunking).
        Each segment = exactly one API call at the model's max duration."""
        # At 60 BPM, beat = 1.0s. max_segment = 10 => split at 10s intervals.
        analysis = {
            "phrases": [
                {"start": 0.0, "end": 25.0, "beats": 25, "energy": 0.8,
                 "spectral_centroid": 4000.0, "label": "drop"},
            ],
            "duration": 25.0,
            "bpm": 60.0,
            "mood": {"mood_descriptor": "test", "quadrant": "euphoric"},
        }
        segments = _plan_segments(analysis, max_segment_duration=10)
        # At 60 BPM: beat=1s. Splits at 10, 20, remainder 5s.
        assert len(segments) == 3
        assert segments[0]["end"] == pytest.approx(10.0, abs=0.01)
        assert segments[1]["end"] == pytest.approx(20.0, abs=0.01)
        assert segments[2]["end"] == pytest.approx(25.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test: No gaps, full coverage
# ---------------------------------------------------------------------------

class TestSegmentCoverage:
    """Verify segments cover the full track with no gaps."""

    def test_no_gaps_between_segments(self, edm_analysis):
        segments = _plan_segments(edm_analysis, max_segment_duration=10)
        for i in range(1, len(segments)):
            assert segments[i]["start"] == pytest.approx(
                segments[i - 1]["end"], abs=0.01
            ), f"Gap between segments {i-1} and {i}"

    def test_covers_full_duration(self, edm_analysis):
        segments = _plan_segments(edm_analysis, max_segment_duration=10)
        assert segments[0]["start"] == 0.0
        assert segments[-1]["end"] == pytest.approx(210.0, abs=0.01)

    def test_all_durations_positive(self, edm_analysis):
        segments = _plan_segments(edm_analysis, max_segment_duration=10)
        for seg in segments:
            assert seg["duration"] > 0, f"Zero/negative duration: {seg}"

    def test_segment_index_sequential(self, edm_analysis):
        segments = _plan_segments(edm_analysis, max_segment_duration=10)
        for i, seg in enumerate(segments):
            assert seg["segment_index"] == i

    def test_empty_phrases_fallback(self):
        analysis = {"phrases": [], "duration": 120.0, "mood": {}}
        segments = _plan_segments(analysis, max_segment_duration=10)
        assert len(segments) == 1
        assert segments[0]["duration"] == 120.0
        assert segments[0]["sub_index"] == 0


# ---------------------------------------------------------------------------
# Test: Label assignment bug fix (single-phrase track)
# ---------------------------------------------------------------------------

class TestLabelPhrasesBug:
    """Verify _label_phrases handles edge cases correctly."""

    def test_single_phrase_labeled_intro_not_outro(self):
        """A single-phrase track must be 'intro', not 'outro' (the bug)."""
        phrases = [
            Phrase(start=0.0, end=30.0, beats=64, energy=0.5,
                   spectral_centroid=2000.0, label=""),
        ]
        _label_phrases(phrases)
        assert phrases[0].label == "intro", (
            f"Single phrase labeled '{phrases[0].label}' instead of 'intro'"
        )

    def test_two_phrases_get_intro_and_outro(self):
        """Two phrases should get intro and outro."""
        phrases = [
            Phrase(start=0.0, end=15.0, beats=32, energy=0.3,
                   spectral_centroid=2000.0, label=""),
            Phrase(start=15.0, end=30.0, beats=32, energy=0.2,
                   spectral_centroid=1500.0, label=""),
        ]
        _label_phrases(phrases)
        assert phrases[0].label == "intro"
        assert phrases[1].label == "outro"

    def test_empty_phrases_no_crash(self):
        """Empty phrase list should not raise."""
        _label_phrases([])


# ---------------------------------------------------------------------------
# Test: Labels preserved through segmentation
# ---------------------------------------------------------------------------

class TestLabelPreservation:
    """Verify phrase labels flow through to segments."""

    def test_labels_match_source_phrases(self, edm_analysis):
        segments = _plan_segments(edm_analysis, max_segment_duration=10)
        for seg in segments:
            assert seg["label"] in (
                "intro", "buildup", "drop", "breakdown", "outro"
            ), f"Unexpected label: {seg['label']}"

    def test_drop_label_preserved_in_splits(self, edm_analysis):
        """All splits of a drop phrase should retain the 'drop' label."""
        segments = _plan_segments(edm_analysis, max_segment_duration=10)
        drop_segs = [s for s in segments if s["start"] >= 30.0 and s["end"] <= 75.01]
        for seg in drop_segs:
            assert seg["label"] == "drop"
