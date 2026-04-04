"""Tests for multi-model pipeline routing."""
import pytest

from src.generator.model_router import (
    DEFAULT_ROUTING,
    FALLBACK_CHAINS,
    ModelChoice,
    RoutingPlan,
    estimate_cost_breakdown,
    get_fallback_chain,
    get_model_routing,
    plan_routing,
    route_section,
)


# ── get_model_routing ────────────────────────────────────────────────

class TestGetModelRouting:
    def test_default_routing(self):
        routing = get_model_routing()
        assert "intro" in routing
        assert "drop" in routing
        assert "breakdown" in routing

    def test_brand_override(self):
        brand = {"model_routing": {"drop": {"model": "veo3", "quality": "high"}}}
        routing = get_model_routing(brand)
        assert routing["drop"]["model"] == "veo3"
        # Other sections should still have defaults
        assert routing["intro"]["model"] == DEFAULT_ROUTING["intro"]["model"]

    def test_brand_simple_format(self):
        brand = {"model_routing": {"intro": "minimax"}}
        routing = get_model_routing(brand)
        assert routing["intro"]["model"] == "minimax"

    def test_empty_brand(self):
        routing = get_model_routing({})
        assert routing == DEFAULT_ROUTING


# ── route_section ────────────────────────────────────────────────────

class TestRouteSection:
    def test_returns_model_choice(self):
        choice = route_section("drop")
        assert isinstance(choice, ModelChoice)
        assert choice.section == "drop"
        assert len(choice.model) > 0

    def test_drop_gets_best_model(self):
        choice = route_section("drop")
        assert "pro" in choice.model or "v2" in choice.model or "v1-5" in choice.model

    def test_intro_gets_cheaper_model(self):
        choice = route_section("intro")
        assert choice.estimated_cost_per_sec <= route_section("drop").estimated_cost_per_sec

    def test_fallback_when_unavailable(self):
        available = {"minimax", "wan2.1-720p"}
        choice = route_section("drop", available_models=available)
        assert choice.model in available
        assert choice.is_fallback

    def test_no_fallback_marker_when_primary_available(self):
        choice = route_section("drop")
        assert not choice.is_fallback

    def test_unknown_section_falls_back_to_drop(self):
        choice = route_section("unknown_section")
        # Should get something (drop defaults)
        assert len(choice.model) > 0

    def test_brand_routing_respected(self):
        brand = {"model_routing": {"drop": {"model": "minimax", "quality": "standard"}}}
        choice = route_section("drop", brand_config=brand)
        assert choice.model == "minimax"


# ── get_fallback_chain ───────────────────────────────────────────────

class TestFallbackChain:
    def test_kling_has_fallbacks(self):
        chain = get_fallback_chain("kling-v1-5-pro")
        assert len(chain) >= 2
        assert all(isinstance(m, str) for m in chain)

    def test_unknown_model_empty_chain(self):
        assert get_fallback_chain("nonexistent-model") == []

    def test_all_models_have_chains(self):
        for model in FALLBACK_CHAINS:
            chain = get_fallback_chain(model)
            assert len(chain) >= 1, f"Model {model} has no fallback chain"
            # No model should fall back to itself
            assert model not in chain, f"Model {model} falls back to itself"


# ── plan_routing ─────────────────────────────────────────────────────

class TestPlanRouting:
    def _make_segments(self):
        return [
            {"label": "intro", "duration": 15.0},
            {"label": "buildup", "duration": 15.0},
            {"label": "drop", "duration": 30.0},
            {"label": "breakdown", "duration": 15.0},
            {"label": "drop", "duration": 30.0},
            {"label": "outro", "duration": 15.0},
        ]

    def test_returns_routing_plan(self):
        plan = plan_routing(self._make_segments())
        assert isinstance(plan, RoutingPlan)
        assert len(plan.choices) == 6

    def test_total_cost_positive(self):
        plan = plan_routing(self._make_segments())
        assert plan.total_estimated_cost > 0

    def test_to_dict(self):
        plan = plan_routing(self._make_segments())
        d = plan.to_dict()
        assert "choices" in d
        assert "total_estimated_cost" in d
        assert len(d["choices"]) == 6

    def test_different_models_per_section(self):
        plan = plan_routing(self._make_segments())
        models = {c.model for c in plan.choices}
        # Should use at least 2 different models with default routing
        assert len(models) >= 2

    def test_brand_override_plan(self):
        brand = {"model_routing": {"drop": {"model": "veo2", "quality": "high"}}}
        plan = plan_routing(self._make_segments(), brand_config=brand)
        drop_choices = [c for c in plan.choices if c.section == "drop"]
        assert all(c.model == "veo2" for c in drop_choices)


# ── estimate_cost_breakdown ──────────────────────────────────────────

class TestEstimateCostBreakdown:
    def _make_segments(self):
        return [
            {"label": "intro", "duration": 15.0},
            {"label": "drop", "duration": 30.0},
            {"label": "outro", "duration": 15.0},
        ]

    def test_returns_breakdown(self):
        result = estimate_cost_breakdown(self._make_segments())
        assert "per_section" in result
        assert "total_cost" in result
        assert "unique_models" in result
        assert len(result["per_section"]) == 3

    def test_per_section_has_details(self):
        result = estimate_cost_breakdown(self._make_segments())
        for section in result["per_section"]:
            assert "label" in section
            assert "model" in section
            assert "cost" in section
            assert "duration" in section

    def test_total_cost_is_sum(self):
        result = estimate_cost_breakdown(self._make_segments())
        section_sum = sum(s["cost"] for s in result["per_section"])
        assert abs(result["total_cost"] - section_sum) < 0.01

    def test_drops_cost_more(self):
        result = estimate_cost_breakdown(self._make_segments())
        intro_cost = result["per_section"][0]["cost"]
        drop_cost = result["per_section"][1]["cost"]
        # Drop uses a more expensive model AND is longer
        assert drop_cost > intro_cost
