"""
A/B visual generation with quality scoring.

Generates 2 candidates per section with prompt variations, scores each
on multiple quality axes, and auto-selects the winner. Losers are
stored as alternates for manual override.

Scoring axes:
1. Prompt adherence (keyword match between prompt and visual descriptors)
2. Technical quality (resolution, bitrate, frame consistency)
3. Color richness (histogram spread, saturation)
4. Motion quality (frame difference variance -- smooth vs. jerky)
5. Brand consistency (similarity to brand's color palette)

Each axis produces 0-100 score. Weighted average determines winner.
"""
import hashlib
import logging
import random
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Score weights
SCORE_WEIGHTS = {
    "prompt_adherence": 0.25,
    "technical_quality": 0.20,
    "color_richness": 0.20,
    "motion_quality": 0.15,
    "brand_consistency": 0.20,
}


@dataclass
class ABCandidate:
    """One candidate in an A/B test."""
    variant: str  # "A" or "B"
    prompt: str
    seed: int = 0
    scores: dict = field(default_factory=dict)
    overall_score: float = 0.0
    file_path: str = ""
    is_winner: bool = False
    generation_cost: float = 0.0

    def to_dict(self) -> dict:
        return {
            "variant": self.variant,
            "prompt": self.prompt,
            "seed": self.seed,
            "scores": self.scores,
            "overall_score": round(self.overall_score, 2),
            "file_path": self.file_path,
            "is_winner": self.is_winner,
            "generation_cost": self.generation_cost,
        }


@dataclass
class ABTestResult:
    """Result of an A/B test for one section."""
    section_label: str
    candidate_a: ABCandidate = field(default_factory=lambda: ABCandidate(variant="A", prompt=""))
    candidate_b: ABCandidate = field(default_factory=lambda: ABCandidate(variant="B", prompt=""))
    winner: str = ""  # "A" or "B"
    auto_selected: bool = True
    total_cost: float = 0.0

    def to_dict(self) -> dict:
        return {
            "section_label": self.section_label,
            "candidate_a": self.candidate_a.to_dict(),
            "candidate_b": self.candidate_b.to_dict(),
            "winner": self.winner,
            "auto_selected": self.auto_selected,
            "total_cost": round(self.total_cost, 4),
        }


def generate_prompt_variants(
    base_prompt: str,
    seed: Optional[int] = None,
) -> tuple[str, str, int, int]:
    """Generate two prompt variants from a base prompt.

    Variant A: original prompt with seed A
    Variant B: slightly modified prompt with seed B
    Modifications: word order shuffle in non-critical parts, synonym swap.

    Args:
        base_prompt: The original generation prompt.
        seed: Optional seed for deterministic variation.

    Returns:
        (prompt_a, prompt_b, seed_a, seed_b)
    """
    if seed is not None:
        rng = random.Random(seed)
    else:
        rng = random.Random()

    seed_a = rng.randint(1, 999999)
    seed_b = rng.randint(1, 999999)

    # Variant A: original prompt
    prompt_a = base_prompt

    # Variant B: rearrange some descriptive parts
    parts = [p.strip() for p in base_prompt.split(",")]

    if len(parts) > 3:
        # Keep first and last parts (usually most important), shuffle middle
        first = parts[0]
        last = parts[-1]
        middle = parts[1:-1]
        rng.shuffle(middle)
        # Add a subtle variation word
        variations = [
            "alternative perspective",
            "different angle",
            "varied composition",
            "reimagined",
            "reinterpreted",
        ]
        middle.append(rng.choice(variations))
        prompt_b = ", ".join([first] + middle + [last])
    else:
        prompt_b = base_prompt + ", alternative visual interpretation"

    return prompt_a, prompt_b, seed_a, seed_b


def score_candidate(
    candidate: ABCandidate,
    brand_palette: Optional[list[str]] = None,
) -> ABCandidate:
    """Score a candidate on all quality axes.

    For now, uses heuristic scoring based on prompt characteristics.
    Full implementation would use CLIP embeddings and frame analysis.

    Args:
        candidate: Candidate to score.
        brand_palette: Brand color palette for consistency scoring.

    Returns:
        Same candidate with scores populated.
    """
    prompt = candidate.prompt.lower()

    # Prompt adherence: based on specificity (more descriptors = better)
    word_count = len(prompt.split())
    unique_words = len(set(prompt.split()))
    specificity = min(100, int(unique_words / max(word_count, 1) * 100 + word_count * 1.5))
    candidate.scores["prompt_adherence"] = min(100, specificity)

    # Technical quality: seed-based pseudo-score (placeholder for real analysis)
    # In production, this would analyze the actual generated image/video
    seed_hash = hashlib.md5(str(candidate.seed).encode()).hexdigest()
    candidate.scores["technical_quality"] = 60 + int(seed_hash[:2], 16) % 40

    # Color richness: based on color-related words in prompt
    color_words = {"vibrant", "neon", "colorful", "iridescent", "prismatic",
                   "golden", "luminous", "bright", "vivid", "saturated"}
    color_score = sum(10 for w in color_words if w in prompt)
    candidate.scores["color_richness"] = min(100, 50 + color_score)

    # Motion quality: based on motion-related descriptors
    motion_words = {"smooth", "fluid", "flowing", "dynamic", "continuous",
                    "gradual", "subtle", "gentle", "explosive", "rapid"}
    motion_score = sum(10 for w in motion_words if w in prompt)
    candidate.scores["motion_quality"] = min(100, 50 + motion_score)

    # Brand consistency: based on palette match (placeholder)
    if brand_palette:
        # Simple: more palette colors mentioned = higher score
        palette_str = " ".join(brand_palette).lower()
        overlap = sum(1 for w in prompt.split() if w in palette_str)
        candidate.scores["brand_consistency"] = min(100, 50 + overlap * 5)
    else:
        candidate.scores["brand_consistency"] = 70

    # Calculate weighted overall
    total = 0.0
    total_weight = 0.0
    for axis, weight in SCORE_WEIGHTS.items():
        if axis in candidate.scores:
            total += candidate.scores[axis] * weight
            total_weight += weight

    candidate.overall_score = total / total_weight if total_weight > 0 else 0

    return candidate


def run_ab_test(
    section_label: str,
    base_prompt: str,
    brand_palette: Optional[list[str]] = None,
    seed: Optional[int] = None,
) -> ABTestResult:
    """Run a complete A/B test for one section.

    Generates two prompt variants, scores both, and selects a winner.

    Args:
        section_label: Song section (intro, drop, etc.)
        base_prompt: Base generation prompt.
        brand_palette: Brand color palette.
        seed: Optional seed for deterministic results.

    Returns:
        ABTestResult with both candidates and winner.
    """
    prompt_a, prompt_b, seed_a, seed_b = generate_prompt_variants(base_prompt, seed)

    candidate_a = ABCandidate(variant="A", prompt=prompt_a, seed=seed_a)
    candidate_b = ABCandidate(variant="B", prompt=prompt_b, seed=seed_b)

    # Score both
    score_candidate(candidate_a, brand_palette)
    score_candidate(candidate_b, brand_palette)

    # Select winner
    if candidate_a.overall_score >= candidate_b.overall_score:
        candidate_a.is_winner = True
        winner = "A"
    else:
        candidate_b.is_winner = True
        winner = "B"

    result = ABTestResult(
        section_label=section_label,
        candidate_a=candidate_a,
        candidate_b=candidate_b,
        winner=winner,
        auto_selected=True,
        total_cost=candidate_a.generation_cost + candidate_b.generation_cost,
    )

    logger.info(
        f"A/B test [{section_label}]: A={candidate_a.overall_score:.0f} "
        f"B={candidate_b.overall_score:.0f} -> Winner={winner}"
    )

    return result


def plan_ab_tests(
    segments: list[dict],
    brand_palette: Optional[list[str]] = None,
) -> list[ABTestResult]:
    """Plan A/B tests for all segments in a track.

    Args:
        segments: List of segments with 'label' and 'prompt'.
        brand_palette: Brand color palette.

    Returns:
        List of ABTestResult, one per segment.
    """
    results = []
    for i, seg in enumerate(segments):
        label = seg.get("label", "drop")
        prompt = seg.get("prompt", "")
        # Use segment index as part of seed for deterministic variation
        seed = hash(f"{prompt}_{i}") % (2**31)

        result = run_ab_test(label, prompt, brand_palette, seed)
        results.append(result)

    return results
