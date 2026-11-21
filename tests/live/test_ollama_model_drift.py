"""Supervised local fit verification for ADR 0010.

Run with:
    SDD4GH_ALLOW_MODEL_LOAD=1 pytest -m live tests/live/test_ollama_model_drift.py

Before the first run, save work, use AC power, close memory-heavy apps, and
leave the machine idle. Without explicit opt-in, the checker only prints a plan.
"""

import os

import pytest

from scripts.check_ollama_model_drift import main


@pytest.mark.live
def test_ollama_model_drift():
    if os.environ.get("SDD4GH_ALLOW_MODEL_LOAD") != "1":
        assert main() in {0, 2}
        return
    assert main(["--verify-fit"]) == 0
