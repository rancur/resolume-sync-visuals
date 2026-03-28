"""Tests for auto-mix style feature."""
from pathlib import Path

import pytest

from src.analyzer.genre import get_auto_mix_styles, GENRE_STYLE_MAP


# All valid style names from the config/styles directory
def _available_styles():
    style_dir = Path(__file__).parent.parent / "config" / "styles"
    return {f.stem for f in style_dir.glob("*.yaml")}


class TestGetAutoMixStyles:
    def test_returns_dict_with_expected_keys(self):
        result = get_auto_mix_styles()
        expected_keys = {"drop", "buildup", "breakdown", "intro", "outro"}
        assert set(result.keys()) == expected_keys

    def test_all_styles_are_valid(self):
        available = _available_styles()
        result = get_auto_mix_styles()
        for label, style_name in result.items():
            assert style_name in available, (
                f"Auto-mix assigned '{style_name}' for '{label}' "
                f"but it is not in available styles: {available}"
            )

    def test_seeded_randomization_is_deterministic(self):
        """Same seed always produces the same style assignments."""
        seed = "abc123deadbeef"
        result1 = get_auto_mix_styles(seed=seed)
        result2 = get_auto_mix_styles(seed=seed)
        assert result1 == result2

    def test_different_seeds_produce_different_results(self):
        """Different seeds should (very likely) produce different assignments."""
        # Try many seed pairs to confirm at least some differ
        seeds = [f"track_{i}" for i in range(20)]
        results = [get_auto_mix_styles(seed=s) for s in seeds]

        # At least some should differ (probability of all 20 being identical is vanishingly small)
        unique_results = set(tuple(sorted(r.items())) for r in results)
        assert len(unique_results) > 1, "All seeds produced identical results"

    def test_no_seed_still_returns_valid_styles(self):
        available = _available_styles()
        result = get_auto_mix_styles(seed=None)
        for label, style_name in result.items():
            assert style_name in available

    def test_drop_styles_are_high_energy(self):
        """Drop styles should be from the high-energy pool."""
        high_energy_styles = {"laser", "fire", "glitch"}
        # Test with many seeds to check the pool
        for i in range(50):
            result = get_auto_mix_styles(seed=f"test_{i}")
            assert result["drop"] in high_energy_styles, (
                f"Drop style '{result['drop']}' not in high-energy pool"
            )

    def test_buildup_styles_are_medium_energy(self):
        """Buildup styles should be from the medium-energy pool."""
        buildup_styles = {"abstract", "cyberpunk", "fractal"}
        for i in range(50):
            result = get_auto_mix_styles(seed=f"test_{i}")
            assert result["buildup"] in buildup_styles

    def test_breakdown_styles_are_low_energy(self):
        """Breakdown styles should be from the chill pool."""
        breakdown_styles = {"nature", "cosmic", "liquid"}
        for i in range(50):
            result = get_auto_mix_styles(seed=f"test_{i}")
            assert result["breakdown"] in breakdown_styles

    def test_intro_outro_styles_are_minimal(self):
        """Intro/outro styles should be from the minimal pool."""
        intro_styles = {"minimal", "cosmic"}
        for i in range(50):
            result = get_auto_mix_styles(seed=f"test_{i}")
            assert result["intro"] in intro_styles
            assert result["outro"] in intro_styles

    def test_values_are_strings(self):
        result = get_auto_mix_styles(seed="test")
        for label, style_name in result.items():
            assert isinstance(style_name, str)
            assert len(style_name) > 0
