"""Tests for genre-specific visual vocabularies (src/analyzer/genre_vocabulary.py)."""
import pytest

from src.analyzer.genre_vocabulary import (
    available_genres,
    clear_cache,
    genre_motion_intensity,
    genre_palette_to_colors,
    genre_to_prompt_fragment,
    load_genre_vocabulary,
    merge_genre_with_brand,
    resolve_genre_name,
    GENRE_ALIASES,
)


@pytest.fixture(autouse=True)
def _clear_vocab_cache():
    """Clear cache before each test."""
    clear_cache()
    yield
    clear_cache()


class TestAvailableGenres:
    def test_at_least_eight_genres(self):
        genres = available_genres()
        assert len(genres) >= 8, f"Expected >= 8 genres, got {len(genres)}: {genres}"

    def test_required_genres_present(self):
        genres = set(available_genres())
        required = {"dnb", "dubstep", "house", "techno", "trance", "140", "breaks", "ambient"}
        missing = required - genres
        assert not missing, f"Missing required genre vocabularies: {missing}"


class TestLoadGenreVocabulary:
    def test_load_existing_genre(self):
        vocab = load_genre_vocabulary("dnb")
        assert vocab is not None
        assert "motion" in vocab
        assert "palette" in vocab
        assert "textures" in vocab

    def test_load_nonexistent_genre_returns_none(self):
        vocab = load_genre_vocabulary("nonexistent_genre_xyz")
        assert vocab is None

    def test_load_via_alias(self):
        vocab = load_genre_vocabulary("Drum & Bass")
        assert vocab is not None
        assert vocab.get("motion", {}).get("pattern") == "fast_cuts"

    def test_case_insensitive(self):
        vocab1 = load_genre_vocabulary("DNB")
        clear_cache()
        vocab2 = load_genre_vocabulary("dnb")
        assert vocab1 is not None
        assert vocab2 is not None
        assert vocab1["motion"]["pattern"] == vocab2["motion"]["pattern"]

    def test_caching_works(self):
        vocab1 = load_genre_vocabulary("house")
        vocab2 = load_genre_vocabulary("house")
        assert vocab1 is vocab2  # Same object from cache

    def test_vocabulary_schema(self):
        """Each genre vocabulary should have the required fields."""
        for genre in available_genres():
            vocab = load_genre_vocabulary(genre)
            assert vocab is not None, f"Failed to load {genre}"
            assert "motion" in vocab, f"{genre} missing 'motion'"
            assert "palette" in vocab, f"{genre} missing 'palette'"
            assert "textures" in vocab, f"{genre} missing 'textures'"
            assert "composition" in vocab, f"{genre} missing 'composition'"
            # Motion should have pattern and intensity
            motion = vocab["motion"]
            assert "pattern" in motion, f"{genre} motion missing 'pattern'"
            assert "intensity" in motion, f"{genre} motion missing 'intensity'"
            # Palette should have colors
            assert len(vocab["palette"]) >= 3, f"{genre} needs >= 3 palette colors"
            # Textures should be a list
            assert isinstance(vocab["textures"], list), f"{genre} textures not a list"
            assert len(vocab["textures"]) >= 3, f"{genre} needs >= 3 textures"


class TestResolveGenreName:
    def test_known_alias(self):
        assert resolve_genre_name("Drum & Bass") == "dnb"
        assert resolve_genre_name("jungle") == "dnb"
        assert resolve_genre_name("breakbeat") == "breaks"

    def test_passthrough_unknown(self):
        assert resolve_genre_name("techno") == "techno"
        assert resolve_genre_name("whatever") == "whatever"

    def test_case_insensitive(self):
        assert resolve_genre_name("DRUM & BASS") == "dnb"


class TestGenreToPromptFragment:
    def test_returns_string_for_known_genre(self):
        fragment = genre_to_prompt_fragment("dnb")
        assert isinstance(fragment, str)
        assert len(fragment) > 20

    def test_contains_motion_info(self):
        fragment = genre_to_prompt_fragment("house")
        assert "smooth" in fragment.lower() or "pan" in fragment.lower()

    def test_contains_textures(self):
        fragment = genre_to_prompt_fragment("techno", section="drop")
        assert "texture" in fragment.lower()

    def test_empty_for_unknown_genre(self):
        fragment = genre_to_prompt_fragment("unknown_genre_xyz")
        assert fragment == ""

    def test_section_varies_reference_style(self):
        drop_frag = genre_to_prompt_fragment("dnb", section="drop")
        breakdown_frag = genre_to_prompt_fragment("dnb", section="breakdown")
        # They should differ (different reference styles picked)
        assert drop_frag != breakdown_frag

    def test_all_sections_produce_output(self):
        for section in ["intro", "buildup", "drop", "breakdown", "outro"]:
            frag = genre_to_prompt_fragment("trance", section=section)
            assert len(frag) > 0, f"Empty fragment for section {section}"


class TestGenrePaletteToColors:
    def test_returns_hex_colors(self):
        colors = genre_palette_to_colors("dnb")
        assert len(colors) >= 3
        for c in colors:
            assert c.startswith("#"), f"Color {c} not a hex color"

    def test_empty_for_unknown(self):
        assert genre_palette_to_colors("nonexistent") == []


class TestGenreMotionIntensity:
    def test_returns_float(self):
        intensity = genre_motion_intensity("dnb")
        assert isinstance(intensity, float)
        assert 0.0 <= intensity <= 1.0

    def test_ambient_lower_than_dnb(self):
        ambient_i = genre_motion_intensity("ambient")
        dnb_i = genre_motion_intensity("dnb")
        assert ambient_i < dnb_i

    def test_default_for_unknown(self):
        assert genre_motion_intensity("nonexistent") == 0.5


class TestMergeGenreWithBrand:
    def test_brand_preserved(self):
        brand = {"name": "TestBrand", "style": {"base": "test style"}}
        merged = merge_genre_with_brand("techno", brand)
        assert merged["name"] == "TestBrand"
        assert merged["style"]["base"] == "test style"

    def test_genre_vocabulary_added(self):
        brand = {"name": "TestBrand"}
        merged = merge_genre_with_brand("house", brand)
        assert "genre_vocabulary" in merged
        assert merged["genre_vocabulary"]["motion"]["pattern"] == "smooth_pan"

    def test_motion_mapping_filled(self):
        brand = {"name": "TestBrand"}
        merged = merge_genre_with_brand("dnb", brand)
        assert "motion_mapping" in merged
        mm = merged["motion_mapping"]
        assert "floor" in mm
        assert "ceiling" in mm
        assert mm["ceiling"] > mm["floor"]

    def test_existing_motion_mapping_preserved(self):
        brand = {"name": "TestBrand", "motion_mapping": {"floor": 1, "ceiling": 5, "curve": "linear"}}
        merged = merge_genre_with_brand("dnb", brand)
        assert merged["motion_mapping"]["floor"] == 1
        assert merged["motion_mapping"]["ceiling"] == 5

    def test_does_not_mutate_original(self):
        brand = {"name": "TestBrand"}
        merge_genre_with_brand("techno", brand)
        assert "genre_vocabulary" not in brand

    def test_unknown_genre_returns_copy(self):
        brand = {"name": "TestBrand"}
        merged = merge_genre_with_brand("nonexistent", brand)
        assert merged["name"] == "TestBrand"
        assert "genre_vocabulary" not in merged


class TestPromptIntegration:
    """Test that genre vocabularies integrate with the prompt builder."""

    def test_build_video_prompt_uses_vocabulary(self):
        from src.generator.prompts import build_video_prompt
        # DNB should produce a prompt with genre vocab content
        prompt = build_video_prompt("drop", genre="dnb")
        # Should contain vocabulary-derived content (not just the old inline dict)
        assert "composition" in prompt.lower() or "texture" in prompt.lower()

    def test_build_video_prompt_falls_back_for_unknown(self):
        from src.generator.prompts import build_video_prompt
        # Unknown genre with partial match should still use inline GENRE_VISUALS
        prompt = build_video_prompt("drop", genre="drum & bass")
        assert len(prompt) > 50

    def test_alias_genre_in_prompt(self):
        from src.generator.prompts import build_video_prompt
        prompt = build_video_prompt("drop", genre="Drum & Bass")
        assert "fast cuts" in prompt.lower() or "tunnel" in prompt.lower() or "industrial" in prompt.lower()
