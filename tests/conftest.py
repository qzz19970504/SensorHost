from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPOSITORY_ROOT / "test" / "golden"

# GUI modules import PyQt6 at collection time.  When the optional PyQt6
# dependency is absent (e.g. a bare protocol-only environment) ignore them so
# ``pytest host/tests`` degrades gracefully instead of aborting the whole run
# with a collection ImportError.  Paths are relative to this conftest directory.
_GUI_TEST_MODULES = [
    "test_app_smoke.py",
    "test_orientation.py",
    "test_packaging.py",
    "test_widgets.py",
]
if importlib.util.find_spec("PyQt6") is None:
    collect_ignore = list(_GUI_TEST_MODULES)

# Make both the installed package source (``sensor_host``) and the repository
# root (``host.tools``) importable regardless of the pytest working directory,
# so ``pytest`` run directly under ``host/`` behaves like ``test_stage1.ps1``.
for _import_root in (str(REPOSITORY_ROOT / "host" / "src"), str(REPOSITORY_ROOT)):
    if _import_root not in sys.path:
        sys.path.insert(0, _import_root)


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
