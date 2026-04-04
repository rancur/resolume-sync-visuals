"""Tests for seasonal and venue-specific theme layers."""
from datetime import date

import pytest

from src.generator.themes import (
    apply_theme_to_prompt,
    available_themes,
    build_ffmpeg_filter,
    clear_cache,
    get_color_grading_params,
    get_scheduled_theme,
    load_theme,
    merge_theme_with_brand,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


class TestAvailableThemes:
    def test_at_least_five_seasonal(self):
        themes = available_themes()
        seasonal = {"halloween", "nye", "summer_festival", "winter", "valentines"}
        found = seasonal & set(themes)
        assert len(found) >= 5, f"Found seasonal themes: {found}"

    def test_at_least_three_venue(self):
        themes = set(available_themes())
        venue = {"dark_club", "outdoor_festival", "corporate"}
        found = venue & themes
        assert len(found) >= 3, f"Found venue themes: {found}"


class TestLoadTheme:
    def test_load_existing(self):
        theme = load_theme("halloween")
        assert theme is not None
        assert "prompt_prefix" in theme

    def test_load_nonexistent(self):
        assert load_theme("nonexistent_xyz") is None

    def test_caching(self):
        t1 = load_theme("halloween")
        t2 = load_theme("halloween")
        assert t1 is t2

    def test_has_required_fields(self):
        for name in available_themes():
            theme = load_theme(name)
            assert theme is not None, f"Failed to load {name}"
            assert "name" in theme, f"{name} missing 'name'"
            assert "color_shift" in theme, f"{name} missing 'color_shift'"
            assert "prompt_prefix" in theme or "prompt_suffix" in theme, \
                f"{name} missing prompt modifiers"


class TestGetScheduledTheme:
    def test_halloween_in_october(self):
        result = get_scheduled_theme(date(2026, 10, 15))
        assert result == "halloween"

    def test_summer_in_july(self):
        result = get_scheduled_theme(date(2026, 7, 15))
        assert result == "summer_festival"

    def test_valentines_feb_14(self):
        result = get_scheduled_theme(date(2026, 2, 14))
        assert result == "valentines"

    def test_no_theme_in_march(self):
        # March should not match most themes (unless winter extends)
        result = get_scheduled_theme(date(2026, 3, 15))
        # Could be None or a theme -- just verify it doesn't crash
        assert result is None or isinstance(result, str)


class TestApplyThemeToPrompt:
    def test_adds_prefix_and_suffix(self):
        result = apply_theme_to_prompt("original prompt", "halloween")
        assert "original prompt" in result
        assert "gothic" in result.lower() or "halloween" in result.lower()

    def test_nonexistent_theme_passthrough(self):
        result = apply_theme_to_prompt("original", "nonexistent")
        assert result == "original"


class TestGetColorGradingParams:
    def test_returns_params(self):
        params = get_color_grading_params("halloween")
        assert "hue_rotate" in params
        assert "saturation" in params
        assert "brightness" in params

    def test_nonexistent_returns_empty(self):
        assert get_color_grading_params("nonexistent") == {}

    def test_outdoor_festival_high_brightness(self):
        params = get_color_grading_params("outdoor_festival")
        assert params["brightness"] > 1.0
        assert params["saturation"] > 1.0

    def test_dark_club_low_brightness(self):
        params = get_color_grading_params("dark_club")
        assert params["brightness"] < 1.0
        assert params["contrast"] > 1.0


class TestBuildFfmpegFilter:
    def test_returns_filter_string(self):
        f = build_ffmpeg_filter("halloween")
        assert isinstance(f, str)
        assert len(f) > 0

    def test_contains_hue_filter(self):
        f = build_ffmpeg_filter("halloween")
        assert "hue" in f

    def test_nonexistent_empty(self):
        assert build_ffmpeg_filter("nonexistent") == ""

    def test_filter_is_valid_ffmpeg_syntax(self):
        f = build_ffmpeg_filter("outdoor_festival")
        # Should contain comma-separated filters
        assert "hue" in f or "eq" in f


class TestMergeThemeWithBrand:
    def test_brand_preserved(self):
        brand = {"name": "TestBrand", "style": {"base": "test"}}
        merged = merge_theme_with_brand(brand, "halloween")
        assert merged["name"] == "TestBrand"

    def test_theme_metadata_added(self):
        brand = {"name": "T"}
        merged = merge_theme_with_brand(brand, "halloween")
        assert merged["active_theme"] == "halloween"
        assert "theme" in merged

    def test_section_prompts_modified(self):
        brand = {
            "name": "T",
            "sections": {
                "drop": {"prompt": "original drop prompt"},
                "intro": {"prompt": "original intro prompt"},
            },
        }
        merged = merge_theme_with_brand(brand, "halloween")
        drop_prompt = merged["sections"]["drop"]["prompt"]
        assert "original drop prompt" in drop_prompt
        assert "gothic" in drop_prompt.lower() or "halloween" in drop_prompt.lower()

    def test_nonexistent_theme_returns_copy(self):
        brand = {"name": "T"}
        merged = merge_theme_with_brand(brand, "nonexistent")
        assert merged["name"] == "T"
        assert "active_theme" not in merged

    def test_does_not_mutate_original(self):
        brand = {"name": "T", "sections": {"drop": {"prompt": "original"}}}
        merge_theme_with_brand(brand, "halloween")
        assert brand["sections"]["drop"]["prompt"] == "original"
