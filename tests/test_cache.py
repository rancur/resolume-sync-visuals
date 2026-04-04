"""Tests for smart keyframe caching."""
import tempfile
from pathlib import Path

import pytest

from src.generator.cache import CacheStats, KeyframeCache


@pytest.fixture
def cache(tmp_path):
    """Create a fresh cache in a temp directory."""
    return KeyframeCache(cache_dir=tmp_path / "cache")


@pytest.fixture
def sample_image(tmp_path):
    """Create a sample image file."""
    img = tmp_path / "test_keyframe.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return img


@pytest.fixture
def sample_video(tmp_path):
    """Create a sample video file."""
    vid = tmp_path / "test_segment.mp4"
    vid.write_bytes(b"\x00\x00\x00\x1c" + b"\x00" * 200)
    return vid


# ── Cache key computation ────────────────────────────────────────────

class TestCacheKey:
    def test_deterministic(self):
        k1 = KeyframeCache.compute_cache_key("test prompt", "model-1", "1080p")
        k2 = KeyframeCache.compute_cache_key("test prompt", "model-1", "1080p")
        assert k1 == k2

    def test_different_prompts(self):
        k1 = KeyframeCache.compute_cache_key("prompt A", "model", "1080p")
        k2 = KeyframeCache.compute_cache_key("prompt B", "model", "1080p")
        assert k1 != k2

    def test_different_models(self):
        k1 = KeyframeCache.compute_cache_key("prompt", "model-1", "1080p")
        k2 = KeyframeCache.compute_cache_key("prompt", "model-2", "1080p")
        assert k1 != k2

    def test_different_resolution(self):
        k1 = KeyframeCache.compute_cache_key("prompt", "model", "1080p")
        k2 = KeyframeCache.compute_cache_key("prompt", "model", "720p")
        assert k1 != k2

    def test_extra_params(self):
        k1 = KeyframeCache.compute_cache_key("prompt", extra_param="a")
        k2 = KeyframeCache.compute_cache_key("prompt", extra_param="b")
        assert k1 != k2

    def test_is_hex_string(self):
        key = KeyframeCache.compute_cache_key("test")
        assert len(key) == 64  # SHA-256
        assert all(c in "0123456789abcdef" for c in key)


# ── Brand hash ───────────────────────────────────────────────────────

class TestBrandHash:
    def test_same_config_same_hash(self):
        config = {"style": {"base": "pixel art"}, "sections": {"drop": {"prompt": "x"}}}
        h1 = KeyframeCache.compute_brand_hash(config)
        h2 = KeyframeCache.compute_brand_hash(config)
        assert h1 == h2

    def test_different_style_different_hash(self):
        c1 = {"style": {"base": "pixel art"}}
        c2 = {"style": {"base": "neon lights"}}
        assert KeyframeCache.compute_brand_hash(c1) != KeyframeCache.compute_brand_hash(c2)

    def test_ignores_metadata(self):
        c1 = {"style": {"base": "pixel art"}, "name": "brand1"}
        c2 = {"style": {"base": "pixel art"}, "name": "brand2"}
        assert KeyframeCache.compute_brand_hash(c1) == KeyframeCache.compute_brand_hash(c2)


# ── Keyframe caching ─────────────────────────────────────────────────

class TestKeyframeCache:
    def test_miss_returns_none(self, cache):
        assert cache.get_keyframe("nonexistent prompt") is None

    def test_put_and_get(self, cache, sample_image):
        cache.put_keyframe("test prompt", sample_image, model="flux", resolution="1080p")
        result = cache.get_keyframe("test prompt", model="flux", resolution="1080p")
        assert result is not None
        assert result.exists()

    def test_different_prompt_misses(self, cache, sample_image):
        cache.put_keyframe("prompt A", sample_image)
        assert cache.get_keyframe("prompt B") is None

    def test_hit_increments_count(self, cache, sample_image):
        cache.put_keyframe("test", sample_image)
        cache.get_keyframe("test")
        cache.get_keyframe("test")
        stats = cache.get_stats()
        assert stats.total_hits >= 2


# ── Segment caching ──────────────────────────────────────────────────

class TestSegmentCache:
    def test_put_and_get_segment(self, cache, sample_video):
        cache.put_segment("motion prompt", sample_video, model="kling")
        result = cache.get_segment("motion prompt", model="kling")
        assert result is not None
        assert result.exists()

    def test_miss_returns_none(self, cache):
        assert cache.get_segment("nonexistent") is None


# ── Brand invalidation ───────────────────────────────────────────────

class TestBrandInvalidation:
    def test_invalidate_removes_entries(self, cache, sample_image):
        brand_hash = "abc123"
        cache.put_keyframe("p1", sample_image, brand_hash=brand_hash)
        cache.put_keyframe("p2", sample_image, brand_hash=brand_hash)
        cache.put_keyframe("p3", sample_image, brand_hash="other")

        count = cache.invalidate_brand(brand_hash)
        assert count == 2
        assert cache.get_keyframe("p1") is None
        assert cache.get_keyframe("p2") is None
        # Other brand entry should remain
        assert cache.get_keyframe("p3") is not None

    def test_invalidate_nonexistent_brand(self, cache):
        assert cache.invalidate_brand("nonexistent") == 0


# ── Clear ────────────────────────────────────────────────────────────

class TestCacheClear:
    def test_clear_all(self, cache, sample_image):
        cache.put_keyframe("p1", sample_image)
        cache.put_keyframe("p2", sample_image)
        count = cache.clear()
        assert count == 2
        assert cache.get_keyframe("p1") is None

    def test_clear_with_age(self, cache, sample_image):
        cache.put_keyframe("recent", sample_image)
        # All entries are "now", so clearing >1 day old should remove nothing
        count = cache.clear(older_than_days=1)
        assert count == 0
        assert cache.get_keyframe("recent") is not None


# ── Statistics ───────────────────────────────────────────────────────

class TestCacheStats:
    def test_empty_cache(self, cache):
        stats = cache.get_stats()
        assert stats.total_entries == 0
        assert stats.total_hits == 0

    def test_counts(self, cache, sample_image, sample_video):
        cache.put_keyframe("kf1", sample_image)
        cache.put_keyframe("kf2", sample_image)
        cache.put_segment("seg1", sample_video)
        stats = cache.get_stats()
        assert stats.total_entries == 3
        assert stats.keyframe_entries == 2
        assert stats.segment_entries == 1

    def test_to_dict(self, cache, sample_image):
        cache.put_keyframe("test", sample_image)
        cache.get_keyframe("test")  # hit
        stats = cache.get_stats()
        d = stats.to_dict()
        assert "total_entries" in d
        assert "hit_rate" in d
        assert "total_size_mb" in d
        assert "estimated_savings_usd" in d

    def test_savings_estimate(self, cache, sample_image, sample_video):
        cache.put_keyframe("kf", sample_image)
        cache.put_segment("seg", sample_video)
        # Create hits
        cache.get_keyframe("kf")
        cache.get_segment("seg")
        stats = cache.get_stats()
        assert stats.estimated_savings > 0


# ── Similar prompt search ────────────────────────────────────────────

class TestFindSimilar:
    def test_exact_match(self, cache, sample_image):
        cache.put_keyframe("dark tunnel industrial metallic", sample_image)
        results = cache.find_similar("dark tunnel industrial metallic", threshold=0.8)
        assert len(results) >= 1

    def test_similar_match(self, cache, sample_image):
        cache.put_keyframe("dark industrial tunnel with metallic surfaces", sample_image)
        results = cache.find_similar("dark tunnel industrial metallic", threshold=0.5)
        assert len(results) >= 1

    def test_no_match_below_threshold(self, cache, sample_image):
        cache.put_keyframe("bright sunny beach tropical", sample_image)
        results = cache.find_similar("dark tunnel industrial", threshold=0.8)
        assert len(results) == 0

    def test_empty_cache(self, cache):
        results = cache.find_similar("anything")
        assert results == []

    def test_limit_respected(self, cache, sample_image):
        for i in range(10):
            cache.put_keyframe(f"word1 word2 word3 extra{i}", sample_image)
        results = cache.find_similar("word1 word2 word3", threshold=0.5, limit=3)
        assert len(results) <= 3


# ── Stale entry handling ─────────────────────────────────────────────

class TestStaleEntries:
    def test_deleted_file_returns_none(self, cache, sample_image):
        cache.put_keyframe("test", sample_image)
        # Get the cached file path and delete it
        result = cache.get_keyframe("test")
        assert result is not None
        result.unlink()
        # Now should return None and clean up the entry
        assert cache.get_keyframe("test") is None
