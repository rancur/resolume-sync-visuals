"""
Music mood and emotion analysis using Essentia pre-trained models.

Detects: happy, sad, aggressive, relaxed, party probabilities.
Derives: valence (positive/negative) and arousal (energy/calm).
Maps to Russell's circumplex model of affect for visual parameter mapping.

Models used:
- Discogs-EffNet: embedding extraction (18MB)
- mood_happy/sad/aggressive/relaxed/party: binary classifiers (~500KB each)

All models run on CPU, fast enough for real-time analysis.
"""
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Path to pre-trained models (relative to project root)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_MODELS_DIR = _PROJECT_ROOT / "models" / "mood"

MOOD_NAMES = ["happy", "sad", "aggressive", "relaxed", "party"]

# Russell's circumplex quadrants
QUADRANT_LABELS = {
    "euphoric": "High valence, high arousal — joyful, exciting, triumphant",
    "tense": "Low valence, high arousal — angry, aggressive, intense",
    "melancholic": "Low valence, low arousal — sad, dark, brooding",
    "serene": "High valence, low arousal — calm, peaceful, dreamy",
}

# Mood-to-quadrant weights for deriving valence/arousal
# These are based on the research mapping of emotional labels to the
# circumplex model dimensions.
_VALENCE_WEIGHTS = {
    "happy": 0.9,
    "party": 0.3,
    "relaxed": 0.4,
    "sad": -0.8,
    "aggressive": -0.3,
}
_AROUSAL_WEIGHTS = {
    "aggressive": 0.8,
    "party": 0.7,
    "happy": 0.3,
    "relaxed": -0.7,
    "sad": -0.4,
}
_VALENCE_NORM = sum(abs(v) for v in _VALENCE_WEIGHTS.values())
_AROUSAL_NORM = sum(abs(v) for v in _AROUSAL_WEIGHTS.values())


@dataclass
class MoodAnalysis:
    """Complete mood analysis result for a track or segment."""
    # Raw mood probabilities (0-1)
    happy: float = 0.0
    sad: float = 0.0
    aggressive: float = 0.0
    relaxed: float = 0.0
    party: float = 0.0

    # Derived dimensions (0-1)
    valence: float = 0.5  # 0=negative, 1=positive
    arousal: float = 0.5  # 0=calm, 1=energetic

    # Classified labels
    dominant_mood: str = ""  # Highest scoring mood
    quadrant: str = ""  # euphoric, tense, melancholic, serene
    mood_descriptor: str = ""  # Human-readable summary

    # Per-segment data (for phrase-level analysis)
    segments: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class MoodAnalyzer:
    """
    Analyze music mood using Essentia pre-trained models.

    Usage:
        analyzer = MoodAnalyzer()
        mood = analyzer.analyze("track.flac")
        print(f"Valence: {mood.valence:.2f}, Arousal: {mood.arousal:.2f}")
        print(f"Quadrant: {mood.quadrant} — {mood.mood_descriptor}")
    """

    def __init__(self, models_dir: Optional[Path] = None):
        self._models_dir = models_dir or DEFAULT_MODELS_DIR
        self._embedding_model = None
        self._mood_models = {}
        self._loaded = False

    def _ensure_loaded(self):
        """Lazy-load models on first use."""
        if self._loaded:
            return

        if not self._models_dir.exists():
            raise FileNotFoundError(
                f"Mood models not found at {self._models_dir}. "
                f"Run the model download script or set MOOD_MODELS_DIR."
            )

        try:
            from essentia.standard import (
                TensorflowPredictEffnetDiscogs,
                TensorflowPredict2D,
            )
        except ImportError:
            raise ImportError(
                "essentia-tensorflow is required for mood analysis. "
                "Install with: pip install essentia-tensorflow"
            )

        # Load embedding model
        emb_path = self._models_dir / "discogs-effnet-bs64-1.pb"
        if not emb_path.exists():
            raise FileNotFoundError(f"Embedding model not found: {emb_path}")

        self._embedding_model = TensorflowPredictEffnetDiscogs(
            graphFilename=str(emb_path),
            output="PartitionedCall:1",
        )

        # Load mood classifiers
        for mood_name in MOOD_NAMES:
            model_path = self._models_dir / f"mood_{mood_name}-discogs-effnet-1.pb"
            if model_path.exists():
                self._mood_models[mood_name] = TensorflowPredict2D(
                    graphFilename=str(model_path),
                    output="model/Softmax",
                )
            else:
                logger.warning(f"Mood model not found: {model_path}")

        self._loaded = True
        logger.info(f"Loaded {len(self._mood_models)} mood models from {self._models_dir}")

    def analyze(self, file_path: str | Path, segment_duration: float = 30.0) -> MoodAnalysis:
        """
        Analyze the mood of an audio track.

        Args:
            file_path: Path to audio file
            segment_duration: Duration of segments for per-phrase analysis (seconds)

        Returns:
            MoodAnalysis with probabilities, valence/arousal, and classifications
        """
        self._ensure_loaded()

        from essentia.standard import MonoLoader

        # Suppress TF logging
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

        audio = MonoLoader(
            filename=str(file_path),
            sampleRate=16000,
            resampleQuality=4,
        )()

        logger.info(f"Mood analysis: {Path(file_path).name} ({len(audio)/16000:.1f}s)")

        # Extract embeddings for full track
        embeddings = self._embedding_model(audio)

        # Get mood probabilities
        moods = {}
        for mood_name, model in self._mood_models.items():
            predictions = model(embeddings)
            # Average across all time frames — column 1 is positive class
            moods[mood_name] = float(np.mean(predictions[:, 1]))

        # Derive valence and arousal
        valence = self._compute_valence(moods)
        arousal = self._compute_arousal(moods)

        # Classify
        dominant = max(moods, key=moods.get) if moods else "unknown"
        quadrant = self._classify_quadrant(valence, arousal)
        descriptor = self._describe_mood(moods, valence, arousal, quadrant)

        # Per-segment analysis
        segments = self._analyze_segments(audio, segment_duration)

        result = MoodAnalysis(
            happy=moods.get("happy", 0),
            sad=moods.get("sad", 0),
            aggressive=moods.get("aggressive", 0),
            relaxed=moods.get("relaxed", 0),
            party=moods.get("party", 0),
            valence=valence,
            arousal=arousal,
            dominant_mood=dominant,
            quadrant=quadrant,
            mood_descriptor=descriptor,
            segments=segments,
        )

        logger.info(f"  Mood: {dominant} (v={valence:.2f} a={arousal:.2f}) — {quadrant}")
        return result

    def analyze_segment(self, audio_array: np.ndarray) -> dict:
        """
        Analyze mood of a raw audio segment (16kHz mono float32).
        Used for per-phrase analysis.
        """
        self._ensure_loaded()

        embeddings = self._embedding_model(audio_array)
        if embeddings.shape[0] == 0:
            return {"valence": 0.5, "arousal": 0.5, "moods": {}}

        moods = {}
        for mood_name, model in self._mood_models.items():
            predictions = model(embeddings)
            moods[mood_name] = float(np.mean(predictions[:, 1]))

        return {
            "valence": self._compute_valence(moods),
            "arousal": self._compute_arousal(moods),
            "moods": moods,
        }

    def _analyze_segments(self, audio: np.ndarray, segment_duration: float) -> list[dict]:
        """Analyze mood per time segment."""
        sr = 16000
        seg_samples = int(segment_duration * sr)
        segments = []

        for start in range(0, len(audio), seg_samples):
            end = min(start + seg_samples, len(audio))
            if end - start < sr:  # Skip segments < 1 second
                continue

            segment_audio = audio[start:end]
            result = self.analyze_segment(segment_audio)
            result["start"] = start / sr
            result["end"] = end / sr
            segments.append(result)

        return segments

    @staticmethod
    def _compute_valence(moods: dict) -> float:
        """Derive valence (0-1) from mood probabilities."""
        raw = sum(moods.get(m, 0) * w for m, w in _VALENCE_WEIGHTS.items()) / _VALENCE_NORM
        return max(0.0, min(1.0, raw + 0.5))

    @staticmethod
    def _compute_arousal(moods: dict) -> float:
        """Derive arousal (0-1) from mood probabilities."""
        raw = sum(moods.get(m, 0) * w for m, w in _AROUSAL_WEIGHTS.items()) / _AROUSAL_NORM
        return max(0.0, min(1.0, raw + 0.5))

    @staticmethod
    def _classify_quadrant(valence: float, arousal: float) -> str:
        """Classify into Russell's circumplex quadrant."""
        if valence >= 0.5 and arousal >= 0.5:
            return "euphoric"
        elif valence < 0.5 and arousal >= 0.5:
            return "tense"
        elif valence < 0.5 and arousal < 0.5:
            return "melancholic"
        else:
            return "serene"

    @staticmethod
    def _describe_mood(moods: dict, valence: float, arousal: float, quadrant: str) -> str:
        """Generate a human-readable mood description for AI prompt enhancement."""
        descriptors = []

        if quadrant == "euphoric":
            if moods.get("party", 0) > 0.7:
                descriptors.append("euphoric festival energy")
            elif moods.get("happy", 0) > 0.8:
                descriptors.append("uplifting and joyful")
            else:
                descriptors.append("bright and energetic")
        elif quadrant == "tense":
            if moods.get("aggressive", 0) > 0.7:
                descriptors.append("dark and aggressive")
            else:
                descriptors.append("intense and driving")
        elif quadrant == "melancholic":
            if moods.get("sad", 0) > 0.6:
                descriptors.append("deeply melancholic")
            else:
                descriptors.append("brooding and introspective")
        elif quadrant == "serene":
            if moods.get("relaxed", 0) > 0.7:
                descriptors.append("peaceful and meditative")
            else:
                descriptors.append("calm and atmospheric")

        # Add intensity modifiers
        if arousal > 0.8:
            descriptors.append("maximum intensity")
        elif arousal > 0.6:
            descriptors.append("high energy")
        elif arousal < 0.3:
            descriptors.append("ambient and minimal")

        return ", ".join(descriptors) if descriptors else "neutral"


# Module-level singleton for convenience
_default_analyzer: Optional[MoodAnalyzer] = None


def analyze_mood(file_path: str | Path, segment_duration: float = 30.0) -> MoodAnalysis:
    """
    Convenience function — analyze mood using default models.
    Lazy-loads models on first call.
    """
    global _default_analyzer
    if _default_analyzer is None:
        _default_analyzer = MoodAnalyzer()
    return _default_analyzer.analyze(file_path, segment_duration)
