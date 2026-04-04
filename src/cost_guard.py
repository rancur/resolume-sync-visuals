"""
Per-song cost cap and API waste prevention system.

Prevents runaway spending by:
1. Enforcing per-song cost caps (default $30)
2. Pre-generation cost estimation
3. Smart model downgrade when budget would be exceeded
4. Segment caching to avoid regenerating identical segments
5. Per-call cost logging with running totals
6. WebSocket updates with cost_so_far

This module was created after a $363.70 incident where Veo 2 at $0.50/sec
generated 727 seconds of video with no per-song limit.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default cost cap per song in USD
DEFAULT_MAX_COST_PER_SONG = 30.0

# Model costs per generation (approximate, based on typical segment durations)
# These map model short names to cost per generation call
MODEL_COSTS = {
    # Tier 1 - Premium
    "veo3": {"cost_per_gen": 4.80, "cost_per_sec": 0.60, "max_duration": 8, "tier": 1},
    "veo2": {"cost_per_gen": 4.00, "cost_per_sec": 0.50, "max_duration": 8, "tier": 1},
    "kling-v2": {"cost_per_gen": 0.90, "cost_per_sec": 0.18, "max_duration": 10, "tier": 2},
    "kling-v1-5-pro": {"cost_per_gen": 0.75, "cost_per_sec": 0.15, "max_duration": 10, "tier": 2},
    # Tier 2 - Standard
    "kling-v1": {"cost_per_gen": 0.50, "cost_per_sec": 0.10, "max_duration": 10, "tier": 3},
    "runway-gen3": {"cost_per_gen": 0.50, "cost_per_sec": 0.10, "max_duration": 10, "tier": 3},
    "wan2.1-1080p": {"cost_per_gen": 0.40, "cost_per_sec": 0.08, "max_duration": 5, "tier": 3},
    "minimax": {"cost_per_gen": 0.30, "cost_per_sec": 0.05, "max_duration": 6, "tier": 3},
    "wan2.1-720p": {"cost_per_gen": 0.25, "cost_per_sec": 0.05, "max_duration": 5, "tier": 4},
    "minimax-live": {"cost_per_gen": 0.24, "cost_per_sec": 0.04, "max_duration": 6, "tier": 4},
    # Tier 3 - Budget
    "luma-ray2": {"cost_per_gen": 0.20, "cost_per_sec": 0.04, "max_duration": 9, "tier": 5},
    "pika-2": {"cost_per_gen": 0.20, "cost_per_sec": 0.04, "max_duration": 5, "tier": 5},
    "wan2.1-480p": {"cost_per_gen": 0.15, "cost_per_sec": 0.03, "max_duration": 5, "tier": 5},
    "cogvideox": {"cost_per_gen": 0.12, "cost_per_sec": 0.02, "max_duration": 6, "tier": 6},
    # Keyframe (image) generation
    "fal-ai/flux-lora": {"cost_per_gen": 0.03, "cost_per_sec": 0.0, "max_duration": 0, "tier": 0},
    "fal-ai/flux/schnell": {"cost_per_gen": 0.003, "cost_per_sec": 0.0, "max_duration": 0, "tier": 0},
}

# Downgrade path: ordered from most expensive to cheapest
DOWNGRADE_ORDER = [
    "veo3", "veo2", "kling-v2", "kling-v1-5-pro",
    "kling-v1", "runway-gen3", "wan2.1-1080p", "minimax",
    "wan2.1-720p", "minimax-live", "luma-ray2", "pika-2",
    "wan2.1-480p", "cogvideox",
]


@dataclass
class CostEstimate:
    """Pre-generation cost estimate for a song."""
    model: str
    total_segments: int
    keyframe_cost: float
    video_cost: float
    total_estimated: float
    song_duration: float
    segment_duration: float
    cost_per_segment: float
    exceeds_budget: bool
    budget_limit: float
    suggested_model: Optional[str] = None
    suggested_cost: Optional[float] = None
    warning: Optional[str] = None


@dataclass
class CostGuardState:
    """Running state for cost tracking during a single song generation."""
    track_title: str
    track_id: str = ""
    model: str = ""
    max_cost: float = DEFAULT_MAX_COST_PER_SONG
    cost_so_far: float = 0.0
    segments_completed: int = 0
    segments_total: int = 0
    api_calls: int = 0
    cache_hits: int = 0
    call_log: list = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    auto_downgrade: bool = True
    original_model: str = ""
    downgraded: bool = False
    stopped_by_cap: bool = False


class CostCapExceeded(Exception):
    """Raised when per-song cost cap would be exceeded."""
    def __init__(self, message: str, cost_so_far: float, cap: float):
        super().__init__(message)
        self.cost_so_far = cost_so_far
        self.cap = cap


class CostGuard:
    """
    Per-song cost cap enforcement and budget protection.

    Usage:
        guard = CostGuard(max_cost=30.0, auto_downgrade=True)
        estimate = guard.estimate_cost("kling-v1-5-pro", duration=180, segment_length=5)
        state = guard.start_song("My Track", model="kling-v1-5-pro")
        # Before each API call:
        guard.check_budget(state, estimated_call_cost=0.75)
        # After each API call:
        guard.log_call(state, model="kling-v1-5-pro", cost=0.75, segment_index=0)
    """

    def __init__(
        self,
        max_cost: float = DEFAULT_MAX_COST_PER_SONG,
        auto_downgrade: bool = True,
        cache_dir: Optional[Path] = None,
    ):
        self.max_cost = max_cost
        self.auto_downgrade = auto_downgrade
        self.cache_dir = cache_dir

    def estimate_cost(
        self,
        model: str,
        duration: float,
        segment_length: float = 5.0,
    ) -> CostEstimate:
        """
        Estimate total cost for generating a full song.

        Args:
            model: Video model short name
            duration: Song duration in seconds
            segment_length: Average segment length in seconds

        Returns:
            CostEstimate with breakdown and budget warnings
        """
        model_info = MODEL_COSTS.get(model, {"cost_per_gen": 0.50, "tier": 3})
        cost_per_gen = model_info["cost_per_gen"]
        max_dur = model_info.get("max_duration", 5)

        # Number of segments needed
        effective_segment = min(segment_length, max_dur) if max_dur > 0 else segment_length
        total_segments = max(1, int(duration / effective_segment) + 1)

        # Cost breakdown
        keyframe_cost = total_segments * 0.03  # Flux LoRA per keyframe
        video_cost = total_segments * cost_per_gen
        total_estimated = keyframe_cost + video_cost

        exceeds_budget = total_estimated > self.max_cost
        warning = None
        suggested_model = None
        suggested_cost = None

        if exceeds_budget and self.auto_downgrade:
            # Find a cheaper model that fits the budget
            suggested_model, suggested_cost = self._find_cheaper_model(
                model, duration, effective_segment
            )
            if suggested_model:
                warning = (
                    f"{model} estimated at ${total_estimated:.2f} exceeds "
                    f"${self.max_cost:.2f} cap. Switching to {suggested_model} "
                    f"(est. ${suggested_cost:.2f})"
                )
            else:
                warning = (
                    f"Estimated cost ${total_estimated:.2f} exceeds cap "
                    f"${self.max_cost:.2f}. No cheaper model available. "
                    f"Generation will stop when cap is reached."
                )
        elif exceeds_budget:
            warning = (
                f"Estimated cost ${total_estimated:.2f} exceeds cap "
                f"${self.max_cost:.2f}. Generation will stop when cap is reached."
            )

        return CostEstimate(
            model=model,
            total_segments=total_segments,
            keyframe_cost=keyframe_cost,
            video_cost=video_cost,
            total_estimated=total_estimated,
            song_duration=duration,
            segment_duration=effective_segment,
            cost_per_segment=cost_per_gen + 0.03,
            exceeds_budget=exceeds_budget,
            budget_limit=self.max_cost,
            suggested_model=suggested_model,
            suggested_cost=suggested_cost,
            warning=warning,
        )

    def _find_cheaper_model(
        self, current_model: str, duration: float, segment_length: float
    ) -> tuple[Optional[str], Optional[float]]:
        """Find the best quality model that fits within budget."""
        try:
            current_idx = DOWNGRADE_ORDER.index(current_model)
        except ValueError:
            current_idx = 0

        for model_name in DOWNGRADE_ORDER[current_idx + 1:]:
            info = MODEL_COSTS.get(model_name)
            if not info:
                continue
            max_dur = info.get("max_duration", 5)
            eff_seg = min(segment_length, max_dur) if max_dur > 0 else segment_length
            segs = max(1, int(duration / eff_seg) + 1)
            est = segs * (info["cost_per_gen"] + 0.03)
            if est <= self.max_cost:
                return model_name, est

        return None, None

    def start_song(
        self,
        track_title: str,
        track_id: str = "",
        model: str = "",
        total_segments: int = 0,
    ) -> CostGuardState:
        """Initialize cost tracking for a new song generation."""
        return CostGuardState(
            track_title=track_title,
            track_id=track_id,
            model=model,
            original_model=model,
            max_cost=self.max_cost,
            segments_total=total_segments,
            auto_downgrade=self.auto_downgrade,
        )

    def check_budget(
        self, state: CostGuardState, estimated_call_cost: float
    ) -> str:
        """
        Check if the next API call would exceed the budget.

        Returns:
            "ok" - proceed normally
            "downgrade" - switched to cheaper model (check state.model)
            "stop" - cost cap reached, stop generation

        Raises:
            CostCapExceeded if cap would be exceeded and no downgrade possible
        """
        projected = state.cost_so_far + estimated_call_cost

        if projected <= state.max_cost:
            return "ok"

        # Budget would be exceeded
        if state.auto_downgrade and not state.downgraded:
            # Try to downgrade model
            remaining_budget = state.max_cost - state.cost_so_far
            remaining_segments = max(1, state.segments_total - state.segments_completed)

            for model_name in DOWNGRADE_ORDER:
                info = MODEL_COSTS.get(model_name)
                if not info:
                    continue
                per_seg = info["cost_per_gen"] + 0.03
                if per_seg * remaining_segments <= remaining_budget:
                    old_model = state.model
                    state.model = model_name
                    state.downgraded = True
                    logger.warning(
                        f"Cost guard: auto-downgraded from {old_model} to {model_name} "
                        f"for '{state.track_title}' (${state.cost_so_far:.2f} spent, "
                        f"${state.max_cost:.2f} cap, {remaining_segments} segments remaining)"
                    )
                    return "downgrade"

        # No downgrade possible or auto-downgrade disabled
        state.stopped_by_cap = True
        logger.warning(
            f"Cost guard: STOPPING generation for '{state.track_title}' — "
            f"cap ${state.max_cost:.2f} reached (${state.cost_so_far:.2f} spent)"
        )
        return "stop"

    def log_call(
        self,
        state: CostGuardState,
        model: str,
        cost: float,
        segment_index: int = -1,
        call_type: str = "video",
        cached: bool = False,
    ):
        """Log an API call and update running cost."""
        actual_cost = 0.0 if cached else cost
        state.cost_so_far += actual_cost
        state.api_calls += 1
        if cached:
            state.cache_hits += 1

        state.call_log.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": model,
            "cost": actual_cost,
            "segment_index": segment_index,
            "call_type": call_type,
            "cached": cached,
            "running_total": state.cost_so_far,
            "track_title": state.track_title,
        })

        logger.info(
            f"Cost guard: {call_type} call ${actual_cost:.4f} "
            f"(total: ${state.cost_so_far:.2f} / ${state.max_cost:.2f}) "
            f"[segment {segment_index}, {'cached' if cached else model}]"
        )

    def get_segment_cache_key(
        self, keyframe_hash: str, prompt_hash: str, model: str
    ) -> str:
        """Generate a cache key for a segment to check for duplicates."""
        combined = f"{keyframe_hash}:{prompt_hash}:{model}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def check_segment_cache(
        self, cache_key: str, cache_dir: Optional[Path] = None
    ) -> Optional[Path]:
        """Check if a cached segment exists. Returns path if found."""
        d = cache_dir or self.cache_dir
        if not d:
            return None
        cached_path = d / f"{cache_key}.mp4"
        if cached_path.exists() and cached_path.stat().st_size > 1000:
            return cached_path
        return None

    def save_segment_cache(
        self, cache_key: str, source_path: Path, cache_dir: Optional[Path] = None
    ):
        """Save a generated segment to cache."""
        d = cache_dir or self.cache_dir
        if not d:
            return
        d.mkdir(parents=True, exist_ok=True)
        cached_path = d / f"{cache_key}.mp4"
        try:
            import shutil
            shutil.copy2(source_path, cached_path)
            logger.info(f"Cached segment: {cache_key}")
        except Exception as e:
            logger.warning(f"Failed to cache segment: {e}")

    def summary(self, state: CostGuardState) -> dict:
        """Return a summary dict for the generation run."""
        elapsed = time.time() - state.started_at
        return {
            "track_title": state.track_title,
            "track_id": state.track_id,
            "model_used": state.model,
            "original_model": state.original_model,
            "downgraded": state.downgraded,
            "stopped_by_cap": state.stopped_by_cap,
            "cost_so_far": round(state.cost_so_far, 4),
            "max_cost": state.max_cost,
            "budget_pct": round(state.cost_so_far / state.max_cost * 100, 1) if state.max_cost > 0 else 0,
            "segments_completed": state.segments_completed,
            "segments_total": state.segments_total,
            "api_calls": state.api_calls,
            "cache_hits": state.cache_hits,
            "elapsed_secs": round(elapsed, 1),
        }
