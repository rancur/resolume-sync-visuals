"""
Lyrics and title content analysis for visual generation.

Understands what a song is ABOUT — not just how it sounds — by:
1. Using an LLM to interpret track titles (DJ slang, electronic music culture)
2. Looking up lyrics via Genius API or web search
3. Transcribing vocals via OpenAI Whisper when no lyrics are found online
4. Analyzing lyrical themes to generate visual prompt modifiers

This feeds into the visual generation pipeline so that "Nan Slapper" gets
bass-shockwave visuals instead of generic abstract patterns.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Title Analysis
# ---------------------------------------------------------------------------

_TITLE_ANALYSIS_SYSTEM = """\
You are an expert in electronic music culture, DJ slang, UK bass music,
drum & bass, dubstep, house, techno, and rave culture. When given a track
title (and optionally an artist name), you interpret what the title means
and suggest visual themes that would match the vibe.

You understand slang like: banger, slapper, rinser, wobbler, riddim, reese,
amen, jungle, liquid, neurofunk, halftime, roller, tearout, etc.

Respond ONLY with valid JSON matching this schema (no markdown fences):
{
  "interpretation": "plain-english explanation of what the title means",
  "visual_themes": ["theme1", "theme2", "theme3"],
  "mood_hints": ["mood1", "mood2"],
  "slang_meaning": "if the title uses slang, explain it; otherwise null"
}
"""


def analyze_title(title: str, artist: str = "", *, openai_key: str = "") -> dict:
    """Use an LLM to interpret the song title and suggest visual themes.

    Returns dict with keys: interpretation, visual_themes, mood_hints, slang_meaning.
    Falls back to a basic heuristic result if the API call fails.
    """
    api_key = openai_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("No OPENAI_API_KEY — returning heuristic title analysis")
        return _heuristic_title_analysis(title, artist)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        user_msg = f"Track title: \"{title}\""
        if artist:
            user_msg += f"\nArtist: {artist}"

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _TITLE_ANALYSIS_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.7,
            max_tokens=300,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)

        # Validate expected keys
        for key in ("interpretation", "visual_themes", "mood_hints", "slang_meaning"):
            if key not in result:
                result[key] = [] if key in ("visual_themes", "mood_hints") else ""

        logger.info(f"Title analysis: {result.get('interpretation', '')[:80]}")
        return result

    except Exception as e:
        logger.warning(f"LLM title analysis failed: {e}")
        return _heuristic_title_analysis(title, artist)


def _heuristic_title_analysis(title: str, artist: str = "") -> dict:
    """Basic keyword-based fallback when LLM is unavailable."""
    lower = title.lower()
    themes = []
    moods = []

    keyword_map = {
        "dark": (["darkness", "shadows", "noir"], ["dark", "brooding"]),
        "fire": (["flames", "heat", "burning"], ["intense", "energetic"]),
        "night": (["nighttime", "city lights", "moon"], ["nocturnal", "mysterious"]),
        "bass": (["bass shockwave", "heavy impact", "sub frequencies"], ["heavy", "aggressive"]),
        "slap": (["impact", "shockwave", "force"], ["aggressive", "playful"]),
        "dream": (["dreamscape", "surreal", "floating"], ["dreamy", "ethereal"]),
        "storm": (["lightning", "clouds", "rain"], ["intense", "powerful"]),
        "light": (["radiance", "glow", "illumination"], ["uplifting", "bright"]),
        "deep": (["depth", "abyss", "underwater"], ["deep", "immersive"]),
        "acid": (["psychedelic", "distortion", "neon melting"], ["trippy", "intense"]),
    }

    for keyword, (kthemes, kmoods) in keyword_map.items():
        if keyword in lower:
            themes.extend(kthemes)
            moods.extend(kmoods)

    if not themes:
        themes = ["abstract energy", "rhythmic motion"]
    if not moods:
        moods = ["energetic"]

    return {
        "interpretation": f"Track titled '{title}'" + (f" by {artist}" if artist else ""),
        "visual_themes": themes[:5],
        "mood_hints": moods[:3],
        "slang_meaning": None,
    }


# ---------------------------------------------------------------------------
# Lyrics Lookup (Genius) + Whisper Transcription
# ---------------------------------------------------------------------------

def get_lyrics(title: str, artist: str, *, genius_key: str = "",
               audio_path: Optional[str] = None,
               openai_key: str = "") -> Optional[str]:
    """Try to find lyrics for a track.

    Strategy:
    1. Search Genius API (if GENIUS_API_KEY available)
    2. If no lyrics found and audio_path provided, transcribe with Whisper
    3. Return lyrics text or None
    """
    # Try Genius first
    lyrics = _search_genius(title, artist, genius_key=genius_key)
    if lyrics:
        logger.info(f"Found lyrics via Genius ({len(lyrics)} chars)")
        return lyrics

    # Fallback: Whisper transcription
    if audio_path and os.path.isfile(audio_path):
        lyrics = _transcribe_with_whisper(audio_path, openai_key=openai_key)
        if lyrics:
            logger.info(f"Transcribed lyrics via Whisper ({len(lyrics)} chars)")
            return lyrics

    logger.info("No lyrics found")
    return None


def _search_genius(title: str, artist: str, *, genius_key: str = "") -> Optional[str]:
    """Search Genius API for lyrics."""
    api_key = genius_key or os.environ.get("GENIUS_API_KEY", "")
    if not api_key:
        logger.debug("No GENIUS_API_KEY — skipping Genius search")
        return None

    try:
        import lyricsgenius
    except ImportError:
        logger.debug("lyricsgenius not installed — skipping Genius search")
        return None

    try:
        genius = lyricsgenius.Genius(api_key, verbose=False, timeout=10)
        song = genius.search_song(title, artist)
        if song and song.lyrics:
            # Clean up Genius formatting artifacts
            lyrics = song.lyrics
            # Remove the song title header that Genius prepends
            lines = lyrics.split("\n")
            if lines and (lines[0].endswith("Lyrics") or "Contributors" in lines[0]):
                lines = lines[1:]
            return "\n".join(lines).strip()
    except Exception as e:
        logger.debug(f"Genius search failed: {e}")

    return None


def _transcribe_with_whisper(audio_path: str, *, openai_key: str = "") -> Optional[str]:
    """Transcribe audio vocals using OpenAI Whisper API."""
    api_key = openai_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.debug("No OPENAI_API_KEY — skipping Whisper transcription")
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        file_path = Path(audio_path)
        # Whisper API has a 25MB limit; check size first
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        if file_size_mb > 25:
            logger.warning(
                f"Audio file too large for Whisper API ({file_size_mb:.1f}MB > 25MB). "
                "Consider using separated vocal stem instead."
            )
            return None

        with open(audio_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",
                language="en",
            )

        text = transcript.strip() if isinstance(transcript, str) else str(transcript).strip()

        # Filter out likely non-lyrical transcriptions (just noise/silence)
        if len(text) < 10 or text.lower() in ("", "you", "yeah", "oh"):
            return None

        return text

    except Exception as e:
        logger.warning(f"Whisper transcription failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Lyrics Analysis
# ---------------------------------------------------------------------------

_LYRICS_ANALYSIS_SYSTEM = """\
You are an expert at analyzing song lyrics for visual themes. Given lyrics,
extract the key themes, suggest specific visual representations, identify
important phrases, and describe the narrative arc.

Focus on imagery that works for abstract VJ visuals — no literal depictions
of people, but emotional/abstract visual translations.

Respond ONLY with valid JSON matching this schema (no markdown fences):
{
  "themes": ["theme1", "theme2", "theme3"],
  "visual_suggestions": ["visual1", "visual2", "visual3"],
  "key_phrases": ["phrase1", "phrase2"],
  "narrative_arc": "description of how the song progresses emotionally",
  "display_moments": [
    {"time_hint": "chorus", "text": "key lyric line", "visual": "visual idea"}
  ]
}
"""


def analyze_lyrics(lyrics: str, *, openai_key: str = "") -> dict:
    """Use LLM to analyze lyrics for visual themes.

    Returns dict with: themes, visual_suggestions, key_phrases,
    narrative_arc, display_moments.
    """
    api_key = openai_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("No OPENAI_API_KEY — returning basic lyrics analysis")
        return _basic_lyrics_analysis(lyrics)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        # Truncate very long lyrics to stay within token limits
        truncated = lyrics[:3000] if len(lyrics) > 3000 else lyrics

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _LYRICS_ANALYSIS_SYSTEM},
                {"role": "user", "content": f"Analyze these lyrics:\n\n{truncated}"},
            ],
            temperature=0.7,
            max_tokens=500,
        )

        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)

        # Validate expected keys
        defaults = {
            "themes": [],
            "visual_suggestions": [],
            "key_phrases": [],
            "narrative_arc": "",
            "display_moments": [],
        }
        for key, default in defaults.items():
            if key not in result:
                result[key] = default

        logger.info(f"Lyrics analysis: {len(result['themes'])} themes found")
        return result

    except Exception as e:
        logger.warning(f"LLM lyrics analysis failed: {e}")
        return _basic_lyrics_analysis(lyrics)


def _basic_lyrics_analysis(lyrics: str) -> dict:
    """Keyword extraction fallback when LLM is unavailable."""
    words = set(re.findall(r"\b[a-z]{4,}\b", lyrics.lower()))
    theme_keywords = {
        "love": "love",
        "heart": "love",
        "dark": "darkness",
        "night": "darkness",
        "light": "illumination",
        "fire": "fire",
        "free": "freedom",
        "dream": "dreams",
        "fall": "falling",
        "fly": "flight",
        "rain": "weather",
        "burn": "fire",
        "lost": "searching",
        "hope": "hope",
        "fear": "fear",
        "break": "destruction",
    }
    themes = list({theme_keywords[w] for w in words if w in theme_keywords})[:5]
    if not themes:
        themes = ["abstract"]

    # Pull some key phrases (lines that look like chorus/hook — short + repeated)
    lines = [l.strip() for l in lyrics.split("\n") if l.strip() and len(l.strip()) > 5]
    key_phrases = lines[:3] if lines else []

    return {
        "themes": themes,
        "visual_suggestions": [f"abstract {t}" for t in themes],
        "key_phrases": key_phrases,
        "narrative_arc": "unable to determine without LLM",
        "display_moments": [],
    }


# ---------------------------------------------------------------------------
# Integration: Prompt Modifier
# ---------------------------------------------------------------------------

def get_content_prompt_modifier(
    title: str,
    artist: str = "",
    lyrics: Optional[str] = None,
    *,
    openai_key: str = "",
) -> str:
    """Get a prompt modifier based on song content analysis.

    This gets prepended to visual generation prompts so that images
    reflect what the song is about, not just how it sounds.

    Returns a string like:
      "visual theme: comically heavy bass impact, exaggerated shockwaves,
       playful aggressive energy, things getting knocked over by bass force"
    """
    api_key = openai_key or os.environ.get("OPENAI_API_KEY", "")

    # Always do title analysis
    title_data = analyze_title(title, artist, openai_key=api_key)

    parts = []

    # Title-derived themes
    visual_themes = title_data.get("visual_themes", [])
    if visual_themes:
        parts.append(f"visual theme: {', '.join(visual_themes)}")

    mood_hints = title_data.get("mood_hints", [])
    if mood_hints:
        parts.append(f"mood: {', '.join(mood_hints)}")

    # Lyrics-derived themes (if lyrics available)
    if lyrics:
        lyrics_data = analyze_lyrics(lyrics, openai_key=api_key)
        lyric_visuals = lyrics_data.get("visual_suggestions", [])
        if lyric_visuals:
            parts.append(f"lyrical imagery: {', '.join(lyric_visuals[:4])}")

        arc = lyrics_data.get("narrative_arc", "")
        if arc and arc != "unable to determine without LLM":
            parts.append(f"narrative arc: {arc}")

    if not parts:
        return ""

    modifier = "; ".join(parts)
    logger.info(f"Content prompt modifier: {modifier[:100]}...")
    return modifier


def full_content_analysis(
    title: str,
    artist: str = "",
    audio_path: Optional[str] = None,
    *,
    openai_key: str = "",
    genius_key: str = "",
) -> dict:
    """Run full content analysis: title + lyrics lookup + analysis.

    Convenience function that combines all steps. Used by the CLI command
    and pipeline integration.

    Returns dict with: title_analysis, lyrics (raw text or None),
    lyrics_analysis (or None), prompt_modifier.
    """
    api_key = openai_key or os.environ.get("OPENAI_API_KEY", "")

    title_analysis = analyze_title(title, artist, openai_key=api_key)

    lyrics = get_lyrics(
        title, artist,
        genius_key=genius_key,
        audio_path=audio_path,
        openai_key=api_key,
    )

    lyrics_analysis = None
    if lyrics:
        lyrics_analysis = analyze_lyrics(lyrics, openai_key=api_key)

    prompt_modifier = get_content_prompt_modifier(
        title, artist, lyrics, openai_key=api_key,
    )

    return {
        "title_analysis": title_analysis,
        "lyrics": lyrics,
        "lyrics_analysis": lyrics_analysis,
        "prompt_modifier": prompt_modifier,
    }
