"""Tests for audio fingerprinting."""
import numpy as np
import pytest
from pathlib import Path

from src.analyzer.fingerprint import (
    fingerprint_from_array,
    compare_fingerprints,
)


class TestFingerprintFromArray:
    def test_consistent_hash(self):
        """Same audio data should produce the same fingerprint."""
        sr = 22050
        audio = np.sin(2 * np.pi * 440 * np.linspace(0, 2.0, sr * 2)).astype(np.float32)
        fp1 = fingerprint_from_array(audio, sr)
        fp2 = fingerprint_from_array(audio, sr)
        assert fp1 == fp2

    def test_different_audio_different_hash(self):
        """Different audio should produce different fingerprints."""
        sr = 22050
        t = np.linspace(0, 2.0, sr * 2).astype(np.float32)
        audio1 = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        audio2 = np.sin(2 * np.pi * 880 * t).astype(np.float32)
        fp1 = fingerprint_from_array(audio1, sr)
        fp2 = fingerprint_from_array(audio2, sr)
        assert fp1 != fp2

    def test_hash_length(self):
        """Fingerprint should be 32 hex chars."""
        sr = 22050
        audio = np.random.randn(sr * 2).astype(np.float32)
        fp = fingerprint_from_array(audio, sr)
        assert len(fp) == 32
        assert all(c in "0123456789abcdef" for c in fp)

    def test_empty_raises(self):
        """Empty audio should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="empty"):
            fingerprint_from_array(np.array([], dtype=np.float32), 22050)

    def test_short_audio(self):
        """Very short audio should still produce a valid fingerprint."""
        sr = 22050
        audio = np.random.randn(100).astype(np.float32)
        fp = fingerprint_from_array(audio, sr)
        assert len(fp) == 32


class TestCompareFingerprints:
    def test_same(self):
        assert compare_fingerprints("abc123", "abc123") is True

    def test_different(self):
        assert compare_fingerprints("abc123", "xyz789") is False
