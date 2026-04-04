"""
Multi-model pipeline: route different AI models per song section.

Maps song sections to optimal video models based on their strengths:
- Drops: best quality model (Kling v1.5 Pro, Kling v2)
- Breakdowns: smooth motion model (Minimax)
- Intros/Outros: cost-efficient model (Wan 2.1)
- Buildups: balanced model (Kling v1)

Supports per-brand routing rules and automatic fallback chains.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# Default model routing when no brand-specific routing is configured
DEFAULT_ROUTING = {
    "intro": {"model": "wan2.1-720p", "quality": "standard"},
    "buildup": {"model": "kling-v1", "quality": "standard"},
    "drop": {"model": "kling-v1-5-pro", "quality": "high"},
    "breakdown": {"model": "minimax", "quality": "standard"},
    "outro": {"model": "wan2.1-720p", "quality": "standard"},
}

# Fallback chains: if primary model fails, try the next in order
FALLBACK_CHAINS = {
    "kling-v2": ["kling-v1-5-pro", "kling-v1", "minimax"],
    "kling-v1-5-pro": ["kling-v1", "kling-v2", "minimax"],
    "kling-v1": ["minimax", "kling-v1-5-pro", "wan2.1-720p"],
    "minimax": ["minimax-live", "kling-v1", "wan2.1-720p"],
    "minimax-live": ["minimax", "kling-v1", "wan2.1-720p"],
    "wan2.1-1080p": ["wan2.1-720p", "wan2.1-480p", "kling-v1"],
    "wan2.1-720p": ["wan2.1-480p", "wan2.1-1080p", "minimax"],
    "wan2.1-480p": ["wan2.1-720p", "minimax-live", "cogvideox"],
    "runway-gen3": ["kling-v1-5-pro", "kling-v1", "minimax"],
    "luma-ray2": ["minimax-live", "wan2.1-720p", "cogvideox"],
    "pika-2": ["minimax-live", "wan2.1-480p", "cogvideox"],
    "cogvideox": ["wan2.1-480p", "minimax-live", "pika-2"],
    "veo2": ["veo3", "kling-v2", "kling-v1-5-pro"],
    "veo3": ["veo2", "kling-v2", "kling-v1-5-pro"],
}


@dataclass
class ModelChoice:
    """Model selection for a specific section."""
    section: str
    model: str
    quality: str
    is_fallback: bool = False
    fallback_from: str = ""
    estimated_cost_per_sec: float = 0.0


@dataclass
class RoutingPlan:
    """Complete model routing plan for a track."""
    choices: list[ModelChoice] = field(default_factory=list)
    total_estimated_cost: float = 0.0

    def to_dict(self) -> dict:
        return {
            "choices": [
                {
                    "section": c.section,
                    "model": c.model,
                    "quality": c.quality,
                    "is_fallback": c.is_fallback,
                    "fallback_from": c.fallback_from,
                    "estimated_cost_per_sec": c.estimated_cost_per_sec,
                }
                for c in self.choices
            ],
            "total_estimated_cost": round(self.total_estimated_cost, 4),
        }


def get_model_routing(brand_config: Optional[dict] = None) -> dict:
    """Get the model routing rules, merging brand config with defaults.

    Brand config takes priority. Missing sections fall back to defaults.

    Args:
        brand_config: Brand guide dict with optional 'model_routing' key.

    Returns:
        Dict mapping section labels to {model, quality}.
    """
    routing = dict(DEFAULT_ROUTING)

    if brand_config:
        brand_routing = brand_config.get("model_routing", {})
        for section, config in brand_routing.items():
            section_lower = section.lower()
            if isinstance(config, dict):
                routing[section_lower] = {
                    "model": config.get("model", routing.get(section_lower, {}).get("model", "kling-v1")),
                    "quality": config.get("quality", routing.get(section_lower, {}).get("quality", "standard")),
                }
            elif isinstance(config, str):
                # Simple format: just model name
                routing[section_lower] = {"model": config, "quality": "standard"}

    return routing


def route_section(
    section_label: str,
    brand_config: Optional[dict] = None,
    available_models: Optional[set[str]] = None,
) -> ModelChoice:
    """Select the best model for a specific section.

    Args:
        section_label: Song section (intro, buildup, drop, breakdown, outro).
        brand_config: Brand guide dict.
        available_models: Set of model IDs that are currently available/configured.
                         If None, all models are assumed available.

    Returns:
        ModelChoice with selected model and quality.
    """
    routing = get_model_routing(brand_config)
    section_lower = section_label.lower()

    # Get the configured choice for this section
    config = routing.get(section_lower, routing.get("drop", DEFAULT_ROUTING["drop"]))
    primary_model = config["model"]
    quality = config["quality"]

    # Check if primary model is available
    if available_models is None or primary_model in available_models:
        return ModelChoice(
            section=section_lower,
            model=primary_model,
            quality=quality,
            estimated_cost_per_sec=_get_cost_per_sec(primary_model),
        )

    # Try fallback chain
    fallbacks = get_fallback_chain(primary_model)
    for fallback in fallbacks:
        if available_models is None or fallback in available_models:
            logger.info(
                f"Model {primary_model} unavailable for {section_lower}, "
                f"falling back to {fallback}"
            )
            return ModelChoice(
                section=section_lower,
                model=fallback,
                quality=quality,
                is_fallback=True,
                fallback_from=primary_model,
                estimated_cost_per_sec=_get_cost_per_sec(fallback),
            )

    # Last resort: use primary anyway (will fail at generation time)
    logger.warning(
        f"No available fallback for {primary_model} on {section_lower}"
    )
    return ModelChoice(
        section=section_lower,
        model=primary_model,
        quality=quality,
        estimated_cost_per_sec=_get_cost_per_sec(primary_model),
    )


def plan_routing(
    segments: list[dict],
    brand_config: Optional[dict] = None,
    available_models: Optional[set[str]] = None,
) -> RoutingPlan:
    """Create a complete routing plan for all segments.

    Args:
        segments: List of segment dicts with at least 'label' and 'duration'.
        brand_config: Brand guide dict.
        available_models: Set of available model IDs.

    Returns:
        RoutingPlan with per-section model choices and cost estimate.
    """
    plan = RoutingPlan()

    for seg in segments:
        label = seg.get("label", "drop")
        duration = seg.get("duration", 10.0)

        choice = route_section(label, brand_config, available_models)
        choice.estimated_cost_per_sec = _get_cost_per_sec(choice.model)
        plan.choices.append(choice)

        plan.total_estimated_cost += choice.estimated_cost_per_sec * duration

    plan.total_estimated_cost = round(plan.total_estimated_cost, 4)
    return plan


def get_fallback_chain(model: str) -> list[str]:
    """Get the fallback chain for a model.

    Args:
        model: Primary model ID.

    Returns:
        Ordered list of fallback model IDs.
    """
    return FALLBACK_CHAINS.get(model, [])


def estimate_cost_breakdown(
    segments: list[dict],
    brand_config: Optional[dict] = None,
) -> dict:
    """Estimate per-section and total cost for a track.

    Args:
        segments: List of segments with 'label' and 'duration'.
        brand_config: Brand guide dict.

    Returns:
        Dict with per_section costs and total.
    """
    plan = plan_routing(segments, brand_config)

    per_section = []
    for seg, choice in zip(segments, plan.choices):
        duration = seg.get("duration", 10.0)
        cost = choice.estimated_cost_per_sec * duration
        per_section.append({
            "label": seg.get("label", "unknown"),
            "model": choice.model,
            "quality": choice.quality,
            "duration": round(duration, 1),
            "cost": round(cost, 4),
        })

    return {
        "per_section": per_section,
        "total_cost": plan.total_estimated_cost,
        "unique_models": list({c.model for c in plan.choices}),
    }


def _get_cost_per_sec(model: str) -> float:
    """Get the cost per second for a model."""
    try:
        from .video_pipeline import SUPPORTED_VIDEO_MODELS
        info = SUPPORTED_VIDEO_MODELS.get(model, {})
        return info.get("cost_per_sec", 0.10)
    except ImportError:
        # Fallback costs
        costs = {
            "kling-v1": 0.10,
            "kling-v1-5-pro": 0.15,
            "kling-v2": 0.18,
            "minimax": 0.05,
            "minimax-live": 0.04,
            "wan2.1-480p": 0.03,
            "wan2.1-720p": 0.05,
            "wan2.1-1080p": 0.08,
            "runway-gen3": 0.10,
            "luma-ray2": 0.04,
            "pika-2": 0.04,
            "cogvideox": 0.02,
            "veo2": 0.50,
            "veo3": 0.60,
        }
        return costs.get(model, 0.10)
