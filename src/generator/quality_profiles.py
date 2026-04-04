"""
Quality profiles for progressive rendering.

Maps quality levels (draft/standard/high) to concrete generation parameters:
video model, resolution, keyframe model, cost estimates.

Two-pass workflow:
1. Preview pass: draft quality, generates keyframe images only (no video),
   low resolution, fastest available. Completes in ~30s per track.
2. Final pass: high quality, generates full video segments, 1080p,
   best available model. Keyframes from preview are reused.

Auto-approve mode skips the preview and goes straight to final.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class QualityProfile:
    """Configuration for a specific quality level."""

    name: str
    video_model: str
    image_model: str
    width: int
    height: int
    fps: int
    # Cost multiplier relative to high quality (1.0)
    cost_multiplier: float
    # Whether this generates video segments or just keyframes
    video_enabled: bool
    # Segment duration override (shorter = faster for previews)
    max_segment_duration: float
    # Number of inference steps for keyframe generation
    keyframe_steps: int
    # Guidance scale for keyframe generation
    keyframe_guidance: float
    description: str = ""

    @property
    def resolution_str(self) -> str:
        return f"{self.width}x{self.height}"

    def estimated_cost_per_track(self, duration_seconds: float = 180.0) -> float:
        """Estimate generation cost for a track of given duration."""
        from .video_pipeline import SUPPORTED_VIDEO_MODELS

        model_info = SUPPORTED_VIDEO_MODELS.get(self.video_model, {})
        cost_per_sec = model_info.get("cost_per_sec", 0.10)

        if not self.video_enabled:
            # Keyframe-only: roughly 5 keyframes at ~$0.04 each
            n_keyframes = max(1, int(duration_seconds / 30))
            return n_keyframes * 0.04

        return duration_seconds * cost_per_sec * self.cost_multiplier


# Pre-defined quality profiles
QUALITY_PROFILES: dict[str, QualityProfile] = {
    "draft": QualityProfile(
        name="draft",
        video_model="wan2.1-480p",
        image_model="dall-e-3",
        width=848,
        height=480,
        fps=24,
        cost_multiplier=0.15,
        video_enabled=False,  # Keyframes only for preview
        max_segment_duration=5.0,
        keyframe_steps=20,
        keyframe_guidance=3.0,
        description="Fast preview — keyframe images only, no video. ~30s per track.",
    ),
    "standard": QualityProfile(
        name="standard",
        video_model="kling-v1",
        image_model="dall-e-3",
        width=1280,
        height=720,
        fps=30,
        cost_multiplier=0.5,
        video_enabled=True,
        max_segment_duration=8.0,
        keyframe_steps=24,
        keyframe_guidance=3.5,
        description="Balanced quality — 720p video, good for review. ~5min per track.",
    ),
    "high": QualityProfile(
        name="high",
        video_model="kling-v1-5-pro",
        image_model="dall-e-3",
        width=1920,
        height=1080,
        fps=60,
        cost_multiplier=1.0,
        video_enabled=True,
        max_segment_duration=10.0,
        keyframe_steps=28,
        keyframe_guidance=3.5,
        description="Full quality — 1080p video, best model. ~15min per track.",
    ),
}


def get_quality_profile(quality: str) -> QualityProfile:
    """Get quality profile by name.

    Args:
        quality: One of 'draft', 'standard', 'high'.

    Returns:
        QualityProfile for the given quality level.

    Raises:
        ValueError: If quality name is not recognized.
    """
    profile = QUALITY_PROFILES.get(quality.lower())
    if not profile:
        available = ", ".join(QUALITY_PROFILES.keys())
        raise ValueError(f"Unknown quality '{quality}'. Available: {available}")
    return profile


def estimate_savings(
    track_duration: float,
    preview_quality: str = "draft",
    final_quality: str = "high",
    approval_rate: float = 0.7,
) -> dict:
    """Estimate cost savings from two-pass progressive rendering.

    Args:
        track_duration: Track duration in seconds.
        preview_quality: Quality level for preview pass.
        final_quality: Quality level for final pass.
        approval_rate: Expected fraction of previews approved (0-1).

    Returns:
        Dict with cost breakdown and savings percentage.
    """
    preview_profile = get_quality_profile(preview_quality)
    final_profile = get_quality_profile(final_quality)

    # Without progressive: every track gets full render
    cost_without = final_profile.estimated_cost_per_track(track_duration)

    # With progressive: preview all, only render approved ones
    preview_cost = preview_profile.estimated_cost_per_track(track_duration)
    final_cost = final_profile.estimated_cost_per_track(track_duration)
    cost_with = preview_cost + (approval_rate * final_cost)

    savings = max(0, cost_without - cost_with)
    pct = (savings / cost_without * 100) if cost_without > 0 else 0

    return {
        "without_progressive": round(cost_without, 4),
        "with_progressive": round(cost_with, 4),
        "savings": round(savings, 4),
        "savings_pct": round(pct, 1),
        "preview_cost": round(preview_cost, 4),
        "final_cost": round(final_cost, 4),
        "approval_rate": approval_rate,
    }


@dataclass
class PreviewResult:
    """Result of a preview pass for one track."""

    track_id: str
    track_title: str
    quality: str
    segments: list[dict] = field(default_factory=list)
    keyframe_paths: list[str] = field(default_factory=list)
    estimated_final_cost: float = 0.0
    preview_cost: float = 0.0
    status: str = "pending"  # pending, approved, rejected, regenerating

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "track_title": self.track_title,
            "quality": self.quality,
            "segments": self.segments,
            "keyframe_paths": self.keyframe_paths,
            "estimated_final_cost": self.estimated_final_cost,
            "preview_cost": self.preview_cost,
            "status": self.status,
        }
