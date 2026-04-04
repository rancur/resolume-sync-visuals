"""Tests for lyrics/title content analysis system."""
import json
import os
from unittest.mock import MagicMock, patch, mock_open

import pytest

from src.analyzer.lyrics import (
    analyze_title,
    analyze_lyrics,
    get_lyrics,
    get_content_prompt_modifier,
    full_content_analysis,
    _heuristic_title_analysis,
    _basic_lyrics_analysis,
)


def _mock_openai_response(content: str):
    """Create a mock OpenAI chat completion response."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# Title Analysis
# ---------------------------------------------------------------------------

class TestAnalyzeTitle:
    """Tests for analyze_title()."""

    def test_heuristic_fallback_no_api_key(self):
        """Without an API key, falls back to heuristic analysis."""
        result = analyze_title("Dark Storm", openai_key="")
        assert "visual_themes" in result
        assert "mood_hints" in result
        assert "interpretation" in result
        assert "slang_meaning" in result
        themes = result["visual_themes"]
        assert any("dark" in t or "shadow" in t or "noir" in t for t in themes)
        assert any("lightning" in t or "cloud" in t or "rain" in t for t in themes)

    def test_heuristic_unknown_title(self):
        """Unknown title gets generic themes."""
        result = _heuristic_title_analysis("Xyzzy Wobble", "")
        assert result["visual_themes"]
        assert result["interpretation"] == "Track titled 'Xyzzy Wobble'"

    def test_heuristic_with_artist(self):
        """Artist name included in interpretation."""
        result = _heuristic_title_analysis("Bass Slapper", "DJ Test")
        assert "DJ Test" in result["interpretation"]
        assert any("impact" in t or "shockwave" in t or "bass" in t
                    for t in result["visual_themes"])

    @patch("openai.OpenAI")
    def test_llm_analysis_success(self, mock_openai_cls):
        """LLM call returns structured JSON."""
        mock_client = _mock_openai_response(json.dumps({
            "interpretation": "Bass so heavy it slaps your nan",
            "visual_themes": ["heavy impact", "bass shockwave"],
            "mood_hints": ["aggressive but playful"],
            "slang_meaning": "extremely heavy bass"
        }))
        mock_openai_cls.return_value = mock_client

        result = analyze_title("Nan Slapper", "Test Artist", openai_key="sk-test")

        assert result["interpretation"] == "Bass so heavy it slaps your nan"
        assert "heavy impact" in result["visual_themes"]
        assert result["slang_meaning"] == "extremely heavy bass"

    @patch("openai.OpenAI")
    def test_llm_strips_markdown_fences(self, mock_openai_cls):
        """Markdown code fences in LLM response are stripped."""
        mock_client = _mock_openai_response(
            "```json\n"
            '{"interpretation": "test", "visual_themes": [], '
            '"mood_hints": [], "slang_meaning": null}\n'
            "```"
        )
        mock_openai_cls.return_value = mock_client

        result = analyze_title("Test", openai_key="sk-test")
        assert result["interpretation"] == "test"

    @patch("openai.OpenAI")
    def test_llm_failure_falls_back(self, mock_openai_cls):
        """If LLM raises, falls back to heuristic."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API down")
        mock_openai_cls.return_value = mock_client

        result = analyze_title("Fire Night", openai_key="sk-test")
        assert "visual_themes" in result
        assert any("flame" in t or "heat" in t or "burn" in t
                    for t in result["visual_themes"])


# ---------------------------------------------------------------------------
# Lyrics Lookup
# ---------------------------------------------------------------------------

class TestGetLyrics:
    """Tests for get_lyrics()."""

    def test_no_keys_no_audio_returns_none(self):
        """Without any keys or audio, returns None."""
        result = get_lyrics("Test", "Artist", genius_key="", openai_key="")
        assert result is None

    @patch("src.analyzer.lyrics._search_genius")
    def test_genius_found(self, mock_genius):
        """If Genius finds lyrics, returns them."""
        mock_genius.return_value = "I am the fire\nBurning bright"
        result = get_lyrics("Fire", "Artist", genius_key="test-key")
        assert result == "I am the fire\nBurning bright"

    @patch("os.path.isfile", return_value=True)
    @patch("src.analyzer.lyrics._transcribe_with_whisper")
    @patch("src.analyzer.lyrics._search_genius")
    def test_genius_miss_whisper_fallback(self, mock_genius, mock_whisper, mock_isfile):
        """If Genius fails, tries Whisper transcription."""
        mock_genius.return_value = None
        mock_whisper.return_value = "Let me go into the night"

        result = get_lyrics("Night", "Artist",
                            audio_path="/tmp/test.flac",
                            openai_key="sk-test")
        assert result == "Let me go into the night"
        mock_whisper.assert_called_once()

    @patch("src.analyzer.lyrics._search_genius")
    def test_genius_miss_no_audio_returns_none(self, mock_genius):
        """If Genius fails and no audio provided, returns None."""
        mock_genius.return_value = None
        result = get_lyrics("Test", "Artist")
        assert result is None


# ---------------------------------------------------------------------------
# Lyrics Analysis
# ---------------------------------------------------------------------------

class TestAnalyzeLyrics:
    """Tests for analyze_lyrics()."""

    def test_basic_fallback_no_key(self):
        """Without API key, uses keyword extraction."""
        lyrics = "I dream of love in the dark night\nFire burns bright"
        result = analyze_lyrics(lyrics, openai_key="")
        assert "themes" in result
        assert len(result["themes"]) > 0
        all_themes = " ".join(result["themes"])
        assert any(word in all_themes for word in ["love", "darkness", "fire", "dreams"])

    def test_basic_fallback_empty_lyrics(self):
        """Empty-ish lyrics still returns structure."""
        result = _basic_lyrics_analysis("oh oh oh")
        assert result["themes"] == ["abstract"]

    @patch("openai.OpenAI")
    def test_llm_analysis(self, mock_openai_cls):
        """LLM lyrics analysis returns structured data."""
        mock_client = _mock_openai_response(json.dumps({
            "themes": ["freedom", "darkness"],
            "visual_suggestions": ["chains breaking", "shadows dissolving"],
            "key_phrases": ["let me go", "into the night"],
            "narrative_arc": "starts constrained, ends with release",
            "display_moments": [
                {"time_hint": "chorus", "text": "let me go", "visual": "chains breaking"}
            ]
        }))
        mock_openai_cls.return_value = mock_client

        result = analyze_lyrics("Let me go into the night", openai_key="sk-test")
        assert "freedom" in result["themes"]
        assert len(result["display_moments"]) == 1
        assert result["narrative_arc"] == "starts constrained, ends with release"


# ---------------------------------------------------------------------------
# Prompt Modifier
# ---------------------------------------------------------------------------

class TestPromptModifier:
    """Tests for get_content_prompt_modifier()."""

    def test_returns_string(self):
        """Always returns a string."""
        result = get_content_prompt_modifier("Test Track", openai_key="")
        assert isinstance(result, str)

    def test_includes_visual_themes(self):
        """Modifier includes title-derived visual themes."""
        result = get_content_prompt_modifier("Dark Fire", openai_key="")
        assert "visual theme:" in result

    @patch("src.analyzer.lyrics.analyze_title")
    @patch("src.analyzer.lyrics.analyze_lyrics")
    def test_with_lyrics(self, mock_analyze_lyrics, mock_analyze_title):
        """When lyrics are provided, includes lyrical imagery."""
        mock_analyze_title.return_value = {
            "interpretation": "test",
            "visual_themes": ["darkness"],
            "mood_hints": ["brooding"],
            "slang_meaning": None,
        }
        mock_analyze_lyrics.return_value = {
            "themes": ["freedom"],
            "visual_suggestions": ["birds flying"],
            "key_phrases": ["set me free"],
            "narrative_arc": "liberation",
            "display_moments": [],
        }

        result = get_content_prompt_modifier(
            "Dark Wings", lyrics="Set me free, let me fly",
            openai_key="sk-test",
        )
        assert "lyrical imagery:" in result
        assert "birds flying" in result

    @patch("src.analyzer.lyrics.analyze_title")
    def test_no_lyrics_still_works(self, mock_analyze_title):
        """Without lyrics, modifier is title-only."""
        mock_analyze_title.return_value = {
            "interpretation": "test",
            "visual_themes": ["bass impact"],
            "mood_hints": ["heavy"],
            "slang_meaning": None,
        }
        result = get_content_prompt_modifier("Bass Drop", openai_key="sk-test")
        assert "visual theme:" in result
        assert "bass impact" in result
        assert "lyrical imagery:" not in result


# ---------------------------------------------------------------------------
# Full Content Analysis
# ---------------------------------------------------------------------------

class TestFullContentAnalysis:
    """Tests for full_content_analysis()."""

    @patch("src.analyzer.lyrics.get_content_prompt_modifier")
    @patch("src.analyzer.lyrics.get_lyrics")
    @patch("src.analyzer.lyrics.analyze_title")
    def test_structure(self, mock_title, mock_lyrics, mock_modifier):
        """Returns expected top-level keys."""
        mock_title.return_value = {
            "interpretation": "test",
            "visual_themes": [],
            "mood_hints": [],
            "slang_meaning": None,
        }
        mock_lyrics.return_value = None
        mock_modifier.return_value = "visual theme: test"

        result = full_content_analysis("Test", "Artist", openai_key="sk-test")

        assert "title_analysis" in result
        assert "lyrics" in result
        assert "lyrics_analysis" in result
        assert "prompt_modifier" in result
        assert result["lyrics"] is None
        assert result["lyrics_analysis"] is None

    @patch("src.analyzer.lyrics.analyze_lyrics")
    @patch("src.analyzer.lyrics.get_content_prompt_modifier")
    @patch("src.analyzer.lyrics.get_lyrics")
    @patch("src.analyzer.lyrics.analyze_title")
    def test_with_lyrics_found(self, mock_title, mock_lyrics, mock_modifier, mock_analyze):
        """When lyrics are found, lyrics_analysis is populated."""
        mock_title.return_value = {
            "interpretation": "test",
            "visual_themes": [],
            "mood_hints": [],
            "slang_meaning": None,
        }
        mock_lyrics.return_value = "some lyrics here"
        mock_modifier.return_value = "visual theme: test"
        mock_analyze.return_value = {"themes": ["love"], "visual_suggestions": []}

        result = full_content_analysis("Love Song", "Artist", openai_key="sk-test")

        assert result["lyrics"] == "some lyrics here"
        assert result["lyrics_analysis"] is not None
        assert "love" in result["lyrics_analysis"]["themes"]


# ---------------------------------------------------------------------------
# Whisper Transcription
# ---------------------------------------------------------------------------

class TestWhisperTranscription:
    """Tests for _transcribe_with_whisper()."""

    @patch("os.path.getsize", return_value=30 * 1024 * 1024)
    @patch("openai.OpenAI")
    def test_file_too_large(self, mock_openai_cls, mock_getsize):
        """Files > 25MB are rejected."""
        from src.analyzer.lyrics import _transcribe_with_whisper

        # Mock Path().stat().st_size
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=30 * 1024 * 1024)
            result = _transcribe_with_whisper("/tmp/big.flac", openai_key="sk-test")
        assert result is None

    def test_no_api_key(self):
        """Without API key, returns None."""
        from src.analyzer.lyrics import _transcribe_with_whisper
        result = _transcribe_with_whisper("/tmp/test.flac", openai_key="")
        assert result is None
