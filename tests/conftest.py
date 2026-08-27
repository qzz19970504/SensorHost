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


class IdleFakeTransport:
    def open(self, device_id: str) -> None:
        self.device_id = device_id

    def close(self) -> None:
        pass

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        return b""

    def write_control(self, command: bytes) -> None:
        pass


@pytest.fixture
def fake_transport_factory():
    return IdleFakeTransport
