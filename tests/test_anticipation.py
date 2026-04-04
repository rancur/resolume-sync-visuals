"""Tests for drop prediction and buildup-aware visual anticipation."""
import pytest

from src.analyzer.anticipation import (
    apply_anticipation,
    build_anticipation_prompt_modifier,
    compute_anticipation_motion_boost,
    find_transitions,
    get_anticipation_config,
    DEFAULT_ANTICIPATION_BEATS,
    DEFAULT_ANTICIPATION_INTENSITY,
)


# ── Fixtures ──────────────────────────────────────────────────────────

def _make_segments():
    """Create a realistic EDM segment sequence."""
    return [
        {"label": "intro", "start": 0.0, "end": 15.0, "energy": 0.2, "prompt": "intro visuals"},
        {"label": "buildup", "start": 15.0, "end": 30.0, "energy": 0.5, "prompt": "buildup visuals"},
        {"label": "drop", "start": 30.0, "end": 60.0, "energy": 0.9, "prompt": "drop visuals"},
        {"label": "breakdown", "start": 60.0, "end": 75.0, "energy": 0.3, "prompt": "breakdown visuals"},
        {"label": "buildup", "start": 75.0, "end": 90.0, "energy": 0.6, "prompt": "buildup 2 visuals"},
        {"label": "drop", "start": 90.0, "end": 120.0, "energy": 0.95, "prompt": "drop 2 visuals"},
        {"label": "outro", "start": 120.0, "end": 150.0, "energy": 0.15, "prompt": "outro visuals"},
    ]


# ── get_anticipation_config ──────────────────────────────────────────

class TestGetAnticipationConfig:
    def test_defaults_without_brand(self):
        config = get_anticipation_config()
        assert config["beats"] == DEFAULT_ANTICIPATION_BEATS
        assert config["intensity"] == DEFAULT_ANTICIPATION_INTENSITY

    def test_defaults_with_empty_brand(self):
        config = get_anticipation_config({})
        assert config["beats"] == DEFAULT_ANTICIPATION_BEATS

    def test_custom_brand_config(self):
        brand = {"anticipation": {"beats": 16, "intensity": 0.9, "breakdown_beats": 6}}
        config = get_anticipation_config(brand)
        assert config["beats"] == 16
        assert config["intensity"] == 0.9
        assert config["breakdown_beats"] == 6

    def test_partial_brand_config(self):
        brand = {"anticipation": {"beats": 12}}
        config = get_anticipation_config(brand)
        assert config["beats"] == 12
        assert config["intensity"] == DEFAULT_ANTICIPATION_INTENSITY


# ── find_transitions ─────────────────────────────────────────────────

class TestFindTransitions:
    def test_finds_buildup_to_drop(self):
        segments = _make_segments()
        transitions = find_transitions(segments)
        buildup_drops = [t for t in transitions if t["type"] == "buildup_to_drop"]
        assert len(buildup_drops) == 2

    def test_finds_breakdown_to_next(self):
        segments = _make_segments()
        transitions = find_transitions(segments)
        breakdown_trans = [t for t in transitions if t["type"] == "breakdown_to_next"]
        assert len(breakdown_trans) == 1
        assert breakdown_trans[0]["from_index"] == 3
        assert breakdown_trans[0]["to_index"] == 4

    def test_no_transitions_in_flat_sequence(self):
        segments = [
            {"label": "drop", "start": 0.0, "end": 30.0, "energy": 0.8},
            {"label": "drop", "start": 30.0, "end": 60.0, "energy": 0.9},
        ]
        transitions = find_transitions(segments)
        assert len(transitions) == 0

    def test_energy_jump_calculated(self):
        segments = _make_segments()
        transitions = find_transitions(segments)
        first = transitions[0]
        assert first["energy_jump"] == pytest.approx(0.4, abs=0.01)

    def test_empty_segments(self):
        assert find_transitions([]) == []

    def test_single_segment(self):
        assert find_transitions([{"label": "drop", "start": 0, "end": 30, "energy": 0.9}]) == []


# ── apply_anticipation ───────────────────────────────────────────────

class TestApplyAnticipation:
    def test_adds_anticipation_to_buildups(self):
        segments = _make_segments()
        result = apply_anticipation(segments, bpm=128.0)
        # Buildup at index 1 should have anticipation
        assert "anticipation" in result[1]
        # Buildup at index 4 should have anticipation
        assert "anticipation" in result[4]

    def test_adds_anticipation_to_breakdowns(self):
        segments = _make_segments()
        result = apply_anticipation(segments, bpm=128.0)
        # Breakdown at index 3 (before buildup) should have anticipation
        assert "anticipation" in result[3]

    def test_no_anticipation_on_drops(self):
        segments = _make_segments()
        result = apply_anticipation(segments, bpm=128.0)
        assert "anticipation" not in result[2]
        assert "anticipation" not in result[5]

    def test_anticipation_has_required_fields(self):
        segments = _make_segments()
        result = apply_anticipation(segments, bpm=128.0)
        antic = result[1]["anticipation"]
        assert "target_label" in antic
        assert "target_energy" in antic
        assert "target_prompt" in antic
        assert "window_beats" in antic
        assert "window_seconds" in antic
        assert "anticipation_start" in antic
        assert "blend_intensity" in antic
        assert "transition_type" in antic

    def test_anticipation_target_is_drop(self):
        segments = _make_segments()
        result = apply_anticipation(segments, bpm=128.0)
        antic = result[1]["anticipation"]
        assert antic["target_label"] == "drop"
        assert antic["target_energy"] == 0.9

    def test_window_respects_bpm(self):
        # Use longer buildup so window isn't clamped by segment duration
        segments = [
            {"label": "intro", "start": 0.0, "end": 30.0, "energy": 0.2, "prompt": "intro"},
            {"label": "buildup", "start": 30.0, "end": 90.0, "energy": 0.5, "prompt": "buildup"},
            {"label": "drop", "start": 90.0, "end": 150.0, "energy": 0.9, "prompt": "drop"},
        ]
        import copy
        result_slow = apply_anticipation(copy.deepcopy(segments), bpm=80.0)
        result_fast = apply_anticipation(copy.deepcopy(segments), bpm=170.0)
        # Slower BPM = longer window in seconds
        slow_window = result_slow[1]["anticipation"]["window_seconds"]
        fast_window = result_fast[1]["anticipation"]["window_seconds"]
        assert slow_window > fast_window

    def test_custom_brand_config(self):
        segments = _make_segments()
        brand = {"anticipation": {"beats": 16, "intensity": 0.9}}
        result = apply_anticipation(segments, bpm=128.0, brand_config=brand)
        antic = result[1]["anticipation"]
        assert antic["window_beats"] == 16
        assert antic["blend_intensity"] == 0.9

    def test_short_segment_skipped(self):
        segments = [
            {"label": "buildup", "start": 0.0, "end": 1.0, "energy": 0.5, "prompt": "short"},
            {"label": "drop", "start": 1.0, "end": 30.0, "energy": 0.9, "prompt": "drop"},
        ]
        result = apply_anticipation(segments, bpm=128.0)
        # 1-second buildup is too short for 8-beat anticipation window at 128 BPM
        assert "anticipation" not in result[0]

    def test_does_not_mutate_prompts(self):
        segments = _make_segments()
        original_prompt = segments[1]["prompt"]
        apply_anticipation(segments, bpm=128.0)
        assert segments[1]["prompt"] == original_prompt

    def test_breakdown_lower_intensity(self):
        segments = _make_segments()
        result = apply_anticipation(segments, bpm=128.0)
        buildup_antic = result[1]["anticipation"]
        breakdown_antic = result[3]["anticipation"]
        assert breakdown_antic["blend_intensity"] < buildup_antic["blend_intensity"]


# ── build_anticipation_prompt_modifier ───────────────────────────────

class TestBuildAnticipationPromptModifier:
    def _make_anticipation(self):
        return {
            "target_label": "drop",
            "target_energy": 0.9,
            "blend_intensity": 0.7,
            "energy_jump": 0.4,
            "transition_type": "buildup_to_drop",
        }

    def test_returns_string(self):
        result = build_anticipation_prompt_modifier(self._make_anticipation(), 0.5)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_early_progress_subtle(self):
        result = build_anticipation_prompt_modifier(self._make_anticipation(), 0.1)
        assert "subtle" in result.lower()

    def test_late_progress_intense(self):
        result = build_anticipation_prompt_modifier(self._make_anticipation(), 0.9)
        assert "maximum" in result.lower() or "explosion" in result.lower()

    def test_mid_progress_ramping(self):
        result = build_anticipation_prompt_modifier(self._make_anticipation(), 0.5)
        assert "ramp" in result.lower() or "intensity" in result.lower()

    def test_varies_with_progress(self):
        early = build_anticipation_prompt_modifier(self._make_anticipation(), 0.1)
        late = build_anticipation_prompt_modifier(self._make_anticipation(), 0.9)
        assert early != late

    def test_breakdown_transition(self):
        antic = self._make_anticipation()
        antic["transition_type"] = "breakdown_to_next"
        result = build_anticipation_prompt_modifier(antic, 0.5)
        assert "reawaken" in result.lower() or "foreshadow" in result.lower()

    def test_high_energy_jump_noted(self):
        antic = self._make_anticipation()
        antic["energy_jump"] = 0.5
        result = build_anticipation_prompt_modifier(antic, 0.5)
        assert "dramatic" in result.lower() or "contrast" in result.lower()


# ── compute_anticipation_motion_boost ────────────────────────────────

class TestComputeAnticipationMotionBoost:
    def _make_anticipation(self):
        return {
            "target_energy": 0.9,
            "blend_intensity": 0.7,
        }

    def test_no_boost_at_zero_progress(self):
        result = compute_anticipation_motion_boost(self._make_anticipation(), 0.0, base_motion=5)
        assert result == 5

    def test_boost_at_full_progress(self):
        result = compute_anticipation_motion_boost(self._make_anticipation(), 1.0, base_motion=5)
        assert result > 5

    def test_progressive_increase(self):
        antic = self._make_anticipation()
        values = [compute_anticipation_motion_boost(antic, p, base_motion=4) for p in [0.0, 0.25, 0.5, 0.75, 1.0]]
        # Should be non-decreasing
        for i in range(1, len(values)):
            assert values[i] >= values[i - 1]

    def test_capped_at_10(self):
        antic = {"target_energy": 1.0, "blend_intensity": 1.0}
        result = compute_anticipation_motion_boost(antic, 1.0, base_motion=9)
        assert result <= 10

    def test_never_below_base(self):
        antic = self._make_anticipation()
        for p in [0.0, 0.3, 0.7, 1.0]:
            result = compute_anticipation_motion_boost(antic, p, base_motion=6)
            assert result >= 6
