from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPOSITORY_ROOT / "test" / "golden"


@pytest.fixture
def golden_stream() -> bytes:
    return (GOLDEN_DIR / "stream_v1_frames.bin").read_bytes()
