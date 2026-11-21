"""Explicit live NVIDIA model-drift test.

Verifies docs/adr/0010-opencode-coding-agent.md.

Run only with:
    pytest -m live tests/live/test_nvidia_model_drift.py

It is excluded by the repository's default pytest configuration.
"""

import pytest

from scripts.check_nvidia_model_drift import main


@pytest.mark.live
def test_nvidia_model_drift():
    assert main() == 0
