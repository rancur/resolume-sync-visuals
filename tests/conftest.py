"""Shared pytest configuration and markers for the test suite."""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_api: needs API keys (OpenAI, fal.ai, etc.)")
    config.addinivalue_line("markers", "requires_models: needs Essentia mood models downloaded")
    config.addinivalue_line("markers", "requires_demucs: needs Demucs model for stem separation")
    config.addinivalue_line("markers", "requires_nas: needs NAS access via SSH")
