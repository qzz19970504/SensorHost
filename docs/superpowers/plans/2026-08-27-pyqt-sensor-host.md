# PyQt Sensor Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows PyQt6 host that receives SDF1 over STM32 USB CDC, records the raw stream, plots real-time IIS3DWB XYZ vibration, renders JY61PL orientation without claiming absolute position, and exposes firmware diagnostics and CLI control.

**Architecture:** A Qt-free acquisition core owns transport reads, SDF1 parsing, bounded sample storage, recording, and command serialization. A thin `QObject`/`QThread` adapter runs that core, while the presentation layer polls immutable snapshots at 30 Hz. The first transport is CDC serial; future ESP32 transports implement the same raw-byte interface.

**Tech Stack:** Python 3.12, PyQt6, pyqtgraph, pyqtgraph.opengl, NumPy, pyserial, pytest, pytest-qt.

---

## 1. Scope and File Map

This plan implements only the approved desktop host. ESP32 firmware remains a separate deliverable governed by `docs/ESP32_GATEWAY_REQUIREMENTS.md`.

### Files created

```text
host/
  README.md                         Run, test, hardware and troubleshooting guide
  pyproject.toml                    Package metadata, runtime and test dependencies
  src/sensor_host/
    __init__.py                     Version and package public surface
    app.py                          QApplication composition root
    acquisition/
      __init__.py                   Acquisition public exports
      controller.py                 Qt-free read/parse/record/control loop
      models.py                     Connection, health and UI snapshot models
      sample_store.py               Bounded sample chunks and display decimation
    protocol/
      __init__.py                   Protocol public exports
      sdf1.py                       SDF1 parser and sensor decoders
    storage/
      __init__.py                   Storage public exports
      recorder.py                   Bounded asynchronous raw recorder
      replay.py                     Raw stream replay and metadata reader
    transport/
      __init__.py                   Transport public exports
      base.py                       Transport Protocol and descriptors
      cdc_serial.py                 pyserial CDC adapter
    presentation/
      __init__.py                   Presentation package marker
      app_controller.py             QThread lifecycle and UI-facing signals
      main_window.py                Approved dual-focus layout and top controls
      theme.py                      Colors, fonts and QSS
      vibration_view.py             XYZ time-domain pyqtgraph widget
      orientation_view.py           ZYX orientation math, OpenGL and 2D fallback
      diagnostics_view.py           Firmware/parser/recorder health cards
      console_view.py               Bounded CLI transcript and command input
  tests/
    conftest.py                     Offscreen Qt and golden paths
    test_package.py                 Package smoke test
    test_protocol_golden.py         Shared golden-frame compatibility
    test_sample_store.py            Windowing and decimation tests
    test_recorder_replay.py         Exact bytes and metadata tests
    test_transport.py               CDC adapter tests with fake serial
    test_acquisition_controller.py  Qt-free end-to-end fake transport tests
    test_orientation.py             ZYX rotation and acceleration vector tests
    test_widgets.py                 pytest-qt interaction and state tests
    test_app_smoke.py               Full application composition smoke test
  tools/
    capture_visual_baseline.py      Deterministic UI screenshot helper
    cdc_acceptance.py               Timed hardware acceptance runner
```

### Files modified

```text
.gitignore                          Ignore host venv, caches, sessions and recordings
test/protocol.py                    Compatibility re-export to the host protocol package
test/test_protocol.py               Continue validating the extracted parser
README.md                           Link host quick start and current CDC-only gate
docs/ROADMAP.md                     Mark host tasks complete only after hardware acceptance
docs/plans/2026-08-27-sensor-host-application-design.md
                                     Track acceptance criteria and resolved CSV scope
```

### Dependency boundaries

```text
presentation -> acquisition -> protocol
                         \----> transport
                         \----> storage
```

`protocol`, `transport`, and `storage` must not import PyQt. `presentation` may import only public module entry points. Unit tests target Qt-free modules first; GUI tests are integration tests.

---

### Task 1: Scaffold the installable host package

**Files:**
- Create: `host/pyproject.toml`
- Create: `host/src/sensor_host/__init__.py`
- Create: `host/tests/conftest.py`
- Create: `host/tests/test_package.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write the failing package smoke test**

```python
# host/tests/test_package.py
from sensor_host import __version__


def test_package_has_development_version() -> None:
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Run the test and verify the package is absent**

Run:

```powershell
$py = 'C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m pytest .\host\tests\test_package.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'sensor_host'`.

- [ ] **Step 3: Add packaging and dependency metadata**

```toml
# host/pyproject.toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "stm32-sensor-host"
version = "0.1.0"
description = "PyQt SDF1 acquisition host for STM32F407 sensor firmware"
requires-python = ">=3.11"
dependencies = [
  "numpy>=1.26,<3",
  "pyserial>=3.5,<4",
  "PyQt6>=6.7,<7",
  "pyqtgraph>=0.13.7,<0.15",
  "PyOpenGL>=3.1.7,<4",
]

[project.optional-dependencies]
dev = [
  "pytest>=8,<10",
  "pytest-qt>=4.4,<5",
]

[project.scripts]
stm32-sensor-host = "sensor_host.app:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

```python
# host/src/sensor_host/__init__.py
"""STM32 SDF1 desktop acquisition host."""

__version__ = "0.1.0"
```

```python
# host/tests/conftest.py
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPOSITORY_ROOT / "test" / "golden"
```

Append these exact ignore rules:

```gitignore
host/.venv/
host/.pytest_cache/
host/.coverage
host/**/*.pyc
host/recordings/
host/tests/golden/actual/
```

- [ ] **Step 4: Create the host virtual environment and install the package**

Run:

```powershell
$py = 'C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m venv .\host\.venv
& .\host\.venv\Scripts\python.exe -m pip install -e '.\host[dev]'
```

Expected: editable package, PyQt6, pyqtgraph, pyserial, NumPy, pytest and pytest-qt install without resolver errors.

- [ ] **Step 5: Run the package test**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_package.py -q`

Expected: `1 passed`.

- [ ] **Step 6: Commit**

```powershell
git add .gitignore host/pyproject.toml host/src/sensor_host/__init__.py host/tests/conftest.py host/tests/test_package.py
git commit -m "build: scaffold PyQt sensor host"
```

---

### Task 2: Extract the authoritative SDF1 parser

**Files:**
- Create: `host/src/sensor_host/protocol/__init__.py`
- Create: `host/src/sensor_host/protocol/sdf1.py`
- Create: `host/tests/test_protocol_golden.py`
- Modify: `test/protocol.py`
- Modify: `test/test_protocol.py`

- [ ] **Step 1: Add a failing golden compatibility test**

```python
# host/tests/test_protocol_golden.py
from pathlib import Path

from sensor_host.protocol import MessageType, StreamParser


def test_shared_golden_stream_decodes_in_one_byte_chunks() -> None:
    root = Path(__file__).resolve().parents[2]
    stream = (root / "test" / "golden" / "stream_v1_frames.bin").read_bytes()
    parser = StreamParser()
    frames = []
    for value in stream:
        frames.extend(parser.feed(bytes((value,))))

    assert [frame.message_type for frame in frames] == [
        MessageType.IIS3DWB_FIFO,
        MessageType.JY61PL_SAMPLE,
        MessageType.STATUS,
        MessageType.CLI_RESPONSE,
    ]
    assert [frame.sequence for frame in frames] == [1, 2, 3, 4]
    assert parser.stats.crc_errors == 0


def test_reset_session_clears_sequence_baseline_and_partial_bytes() -> None:
    parser = StreamParser()
    parser.feed(b"SDF")
    parser.reset_session()
    assert parser.buffered_bytes == 0
    assert parser.last_sequence is None
```

- [ ] **Step 2: Run the test and verify imports fail**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_protocol_golden.py -q`

Expected: collection fails because `sensor_host.protocol` does not exist.

- [ ] **Step 3: Move the existing parser into the package and expose it**

Move the complete current contents of `test/protocol.py` to `host/src/sensor_host/protocol/sdf1.py`. Add these members to `StreamParser`:

```python
    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    @property
    def last_sequence(self) -> int | None:
        return self._last_sequence

    def reset_session(self) -> None:
        self.stats = ParserStats()
        self._buffer.clear()
        self._last_sequence = None
        self._iis_time = IisTimestampReconstructor()
```

Expose the public protocol contract:

```python
# host/src/sensor_host/protocol/__init__.py
from .sdf1 import (
    Frame,
    IisFifoWord,
    IisSample,
    Jy61plSample,
    MessageType,
    ParserStats,
    StatusV1,
    StreamParser,
)

__all__ = [
    "Frame",
    "IisFifoWord",
    "IisSample",
    "Jy61plSample",
    "MessageType",
    "ParserStats",
    "StatusV1",
    "StreamParser",
]
```

Keep firmware-side tests compatible through a re-export:

```python
# test/protocol.py
"""Compatibility import for the installable host SDF1 protocol package."""

from sensor_host.protocol.sdf1 import *  # noqa: F403
```

Add the package source path at the top of `test/test_protocol.py` before importing `protocol`, so root firmware tests run without requiring installation:

```python
import sys

HOST_SRC = Path(__file__).resolve().parents[1] / "host" / "src"
sys.path.insert(0, str(HOST_SRC))
```

- [ ] **Step 4: Run both protocol suites**

Run:

```powershell
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_protocol_golden.py .\test\test_protocol.py -q
```

Expected: all existing protocol tests plus the two new tests pass.

- [ ] **Step 5: Commit**

```powershell
git add host/src/sensor_host/protocol host/tests/test_protocol_golden.py test/protocol.py test/test_protocol.py
git commit -m "refactor: share authoritative SDF1 parser"
```

---

### Task 3: Build bounded real-time sample storage

**Files:**
- Create: `host/src/sensor_host/acquisition/__init__.py`
- Create: `host/src/sensor_host/acquisition/models.py`
- Create: `host/src/sensor_host/acquisition/sample_store.py`
- Create: `host/tests/test_sample_store.py`

- [ ] **Step 1: Write failing window and decimation tests**

```python
# host/tests/test_sample_store.py
import numpy as np

from sensor_host.acquisition import RealtimeSampleStore
from sensor_host.protocol import IisSample, Jy61plSample


def sample(timestamp_us: float, x: int) -> IisSample:
    return IisSample(timestamp_us, (x, -x, x // 2), (x * 0.000061, -x * 0.000061, x * 0.0000305))


def test_snapshot_keeps_requested_window_and_point_budget() -> None:
    store = RealtimeSampleStore(retention_s=30.0)
    store.append_iis(tuple(sample(index * 1_000.0, index) for index in range(20_000)))

    snapshot = store.snapshot(window_s=5.0, max_points=800)

    assert snapshot.time_s.size <= 800
    assert snapshot.time_s[0] >= -5.0
    assert snapshot.time_s[-1] == 0.0
    assert np.max(snapshot.x_g) == 19_999 * 0.000061


def test_latest_orientation_is_reported_with_age() -> None:
    store = RealtimeSampleStore(retention_s=30.0)
    jy = Jy61plSample((1, 2, 3, 2500, 4, 5, 6), (0.1, 0.2, 0.9), 25.0, (10.0, 20.0, 30.0))
    store.update_jy(jy, received_monotonic_s=100.0)

    snapshot = store.snapshot(window_s=5.0, max_points=800, now_monotonic_s=100.4)

    assert snapshot.orientation is not None
    assert snapshot.orientation.angles_deg == (10.0, 20.0, 30.0)
    assert snapshot.orientation_age_s == 0.4
```

- [ ] **Step 2: Run and verify failure**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_sample_store.py -q`

Expected: import fails because `RealtimeSampleStore` is absent.

- [ ] **Step 3: Define immutable UI models**

```python
# host/src/sensor_host/acquisition/models.py
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from sensor_host.protocol import Jy61plSample, ParserStats, StatusV1


@dataclass(frozen=True)
class UiSnapshot:
    time_s: NDArray[np.float64]
    x_g: NDArray[np.float64]
    y_g: NDArray[np.float64]
    z_g: NDArray[np.float64]
    orientation: Jy61plSample | None
    orientation_age_s: float | None
    firmware_status: StatusV1 | None
    parser_stats: ParserStats
    sample_rate_hz: float
```

- [ ] **Step 4: Implement chunked retention and bounded peak-preserving decimation**

Use a deque of NumPy chunks. On append, convert each `IisSample` tuple once. Prune chunks whose final timestamp is older than `latest_timestamp - retention_s`. For snapshots, concatenate only intersecting chunks, make time relative to the newest sample, and select at most `max_points` indices.

The selection function must preserve extrema across all three channels:

```python
def envelope_indices(values: np.ndarray, max_points: int) -> np.ndarray:
    count = values.shape[0]
    if count <= max_points:
        return np.arange(count, dtype=np.int64)
    bucket_count = max(1, max_points // 2)
    edges = np.linspace(0, count, bucket_count + 1, dtype=np.int64)
    selected: list[int] = []
    magnitude = np.max(np.abs(values), axis=1)
    for start, stop in zip(edges[:-1], edges[1:]):
        if stop <= start:
            continue
        local = magnitude[start:stop]
        selected.extend((start + int(np.argmin(local)), start + int(np.argmax(local))))
    return np.asarray(sorted(set(selected)), dtype=np.int64)[:max_points]
```

`RealtimeSampleStore` must also implement:

```python
def update_jy(self, sample: Jy61plSample, received_monotonic_s: float | None = None) -> None: ...
def update_status(self, status: StatusV1) -> None: ...
def update_parser_stats(self, stats: ParserStats) -> None: ...
def snapshot(self, window_s: float, max_points: int, now_monotonic_s: float | None = None) -> UiSnapshot: ...
```

Protect mutations and snapshot extraction with one `threading.Lock`. Return copied arrays and a copied `ParserStats`, never shared mutable state.

Expose `RealtimeSampleStore` and `UiSnapshot` from `acquisition/__init__.py`.

- [ ] **Step 5: Run tests**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_sample_store.py -q`

Expected: both tests pass and the snapshot never exceeds 800 points.

- [ ] **Step 6: Commit**

```powershell
git add host/src/sensor_host/acquisition host/tests/test_sample_store.py
git commit -m "feat: add bounded realtime sample store"
```

---

### Task 4: Add exact raw recording and replay

**Files:**
- Create: `host/src/sensor_host/storage/__init__.py`
- Create: `host/src/sensor_host/storage/recorder.py`
- Create: `host/src/sensor_host/storage/replay.py`
- Create: `host/tests/test_recorder_replay.py`

- [ ] **Step 1: Write failing exact-byte and overflow tests**

```python
# host/tests/test_recorder_replay.py
import json
from pathlib import Path

from sensor_host.storage import RawSessionRecorder, replay_chunks


def test_recorder_preserves_exact_input_and_writes_metadata(tmp_path: Path) -> None:
    path = tmp_path / "session.sdf1"
    recorder = RawSessionRecorder(queue_capacity_bytes=1024)
    recorder.start(path, {"protocol": "SDF1", "version": 1})
    recorder.submit(b"SDF")
    recorder.submit(b"1-payload")
    summary = recorder.stop()

    assert path.read_bytes() == b"SDF1-payload"
    metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert metadata["bytes_written"] == len(b"SDF1-payload")
    assert summary.bytes_written == len(b"SDF1-payload")
    assert b"".join(replay_chunks(path, chunk_size=3)) == b"SDF1-payload"


def test_queue_overflow_stops_recording_without_blocking(tmp_path: Path) -> None:
    recorder = RawSessionRecorder(queue_capacity_bytes=4, start_writer=False)
    recorder.start(tmp_path / "overflow.sdf1", {})

    assert recorder.submit(b"1234") is True
    assert recorder.submit(b"5") is False
    assert recorder.failure == "recording queue capacity exceeded"
```

- [ ] **Step 2: Run and verify failure**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_recorder_replay.py -q`

Expected: storage imports fail.

- [ ] **Step 3: Implement a bounded writer**

`RawSessionRecorder` owns a `queue.Queue[bytes | None]`, a byte-capacity counter protected by a lock, and one writer thread. `submit()` copies the chunk with `bytes(chunk)`, checks capacity, and returns immediately. On capacity overflow it records the exact failure string from the test and rejects future chunks.

Use this summary model:

```python
@dataclass(frozen=True)
class RecordingSummary:
    path: Path
    bytes_written: int
    started_utc: str
    ended_utc: str
    failure: str | None
```

Write metadata first to `<name>.json.tmp`, flush and close it, then replace `<name>.json` with `Path.replace()`. Include `started_utc`, `ended_utc`, `bytes_written`, `failure` and the caller metadata. `stop()` joins the writer for at most five seconds and raises `RuntimeError` if it remains alive.

`replay_chunks(path, chunk_size)` validates `chunk_size > 0` and yields bounded bytes until EOF:

```python
def replay_chunks(path: Path, chunk_size: int = 65536) -> Iterator[bytes]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            yield chunk
```

- [ ] **Step 4: Run tests**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_recorder_replay.py -q`

Expected: both tests pass without sleeping or timing-dependent assertions.

- [ ] **Step 5: Commit**

```powershell
git add host/src/sensor_host/storage host/tests/test_recorder_replay.py
git commit -m "feat: record and replay raw SDF1 sessions"
```

---

### Task 5: Define the transport contract and CDC adapter

**Files:**
- Create: `host/src/sensor_host/transport/__init__.py`
- Create: `host/src/sensor_host/transport/base.py`
- Create: `host/src/sensor_host/transport/cdc_serial.py`
- Create: `host/tests/test_transport.py`

- [ ] **Step 1: Write failing discovery, line-write and close tests**

```python
# host/tests/test_transport.py
from sensor_host.transport import CdcSerialTransport


class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.writes = []
        self.closed = False
        self.in_waiting = 3

    def read(self, count: int) -> bytes:
        return b"abc"[:count]

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def close(self) -> None:
        self.closed = True


def test_cdc_adapter_reads_and_normalizes_control_line() -> None:
    fake = FakeSerial()
    transport = CdcSerialTransport(serial_factory=lambda **_: fake)
    transport.open("COM7")

    assert transport.read(64, 0.05) == b"abc"
    transport.write_control(b"status\n")
    assert fake.writes == [b"status\r\n"]
    transport.close()
    assert fake.closed is True
```

- [ ] **Step 2: Run and verify failure**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_transport.py -q`

Expected: transport imports fail.

- [ ] **Step 3: Define the transport interface**

```python
# host/src/sensor_host/transport/base.py
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DeviceDescriptor:
    device_id: str
    label: str
    vid: int | None = None
    pid: int | None = None


class Transport(Protocol):
    def discover(self) -> list[DeviceDescriptor]: ...
    def open(self, device_id: str) -> None: ...
    def close(self) -> None: ...
    def read(self, max_bytes: int, timeout_s: float) -> bytes: ...
    def write_control(self, command: bytes) -> None: ...
```

- [ ] **Step 4: Implement CDC behavior**

`CdcSerialTransport` uses `serial.tools.list_ports.comports()` for discovery and `serial.Serial(port=device_id, baudrate=115200, timeout=timeout_s)` for opening. The baud value is a conventional CDC setting and does not represent USB line speed.

`read()` reads `min(max_bytes, max(1, in_waiting))`. `write_control()` rejects embedded NUL, strips trailing CR/LF, rejects empty or more than 94 content bytes, then appends exactly `b"\r\n"`. All public operations raise a local `TransportError` with the device id and original pyserial error chained.

- [ ] **Step 5: Run tests**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_transport.py -q`

Expected: adapter test passes without real hardware.

- [ ] **Step 6: Commit**

```powershell
git add host/src/sensor_host/transport host/tests/test_transport.py
git commit -m "feat: add CDC transport adapter"
```

---

### Task 6: Implement the Qt-free acquisition engine

**Files:**
- Modify: `host/src/sensor_host/acquisition/models.py`
- Create: `host/src/sensor_host/acquisition/controller.py`
- Modify: `host/src/sensor_host/acquisition/__init__.py`
- Create: `host/tests/test_acquisition_controller.py`

- [ ] **Step 1: Write a failing fake-transport end-to-end test**

```python
# host/tests/test_acquisition_controller.py
from pathlib import Path
from threading import Event, Thread

from sensor_host.acquisition import AcquisitionController, RealtimeSampleStore
from sensor_host.protocol import MessageType


class FakeTransport:
    def __init__(self, chunks: list[bytes]):
        self.chunks = iter(chunks)
        self.commands: list[bytes] = []
        self.closed = False

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        try:
            return next(self.chunks)
        except StopIteration:
            return b""

    def write_control(self, command: bytes) -> None:
        self.commands.append(command)

    def close(self) -> None:
        self.closed = True


def test_engine_parses_golden_updates_store_and_serializes_commands(golden_stream: bytes) -> None:
    transport = FakeTransport([golden_stream])
    store = RealtimeSampleStore()
    stop = Event()
    controller = AcquisitionController(transport, store)
    controller.enqueue_command("status")
    controller.run(stop, idle_limit=2)

    assert transport.commands == [b"status"]
    assert store.snapshot(10.0, 100).parser_stats.frames == 4
    assert controller.health.bytes_received == len(golden_stream)
    assert transport.closed is True
```

Add this fixture to `host/tests/conftest.py`:

```python
import pytest


@pytest.fixture
def golden_stream() -> bytes:
    return (GOLDEN_DIR / "stream_v1_frames.bin").read_bytes()
```

- [ ] **Step 2: Run and verify failure**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_acquisition_controller.py -q`

Expected: `AcquisitionController` import fails.

- [ ] **Step 3: Implement health and state models**

Add:

```python
@dataclass(frozen=True)
class AcquisitionHealth:
    bytes_received: int = 0
    frames_received: int = 0
    recording_failure: str | None = None
    last_error: str | None = None


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
```

- [ ] **Step 4: Implement the loop and command helpers**

`AcquisitionController` owns one `StreamParser`, one `queue.Queue[bytes]`, the `RealtimeSampleStore`, optional `RawSessionRecorder`, and one `Transport`. The loop order is:

1. Drain all queued commands through `write_control()`.
2. Read at most 64 KiB with a 50 ms timeout.
3. Submit the unchanged chunk to the active recorder before parsing.
4. Feed the chunk to `StreamParser`.
5. Append IIS samples, update JY, STATUS and parser stats.
6. On stop, close transport and stop recorder in `finally`.

Use these public methods:

```python
def enqueue_command(self, command: str) -> None:
    encoded = command.strip().encode("ascii", errors="strict")
    if not encoded or len(encoded) > 94 or b"\x00" in encoded:
        raise ValueError("command must contain 1..94 ASCII bytes without NUL")
    self._commands.put(encoded)

def start_acquisition(self) -> None:
    self.enqueue_command("acq start")

def stop_acquisition(self) -> None:
    self.enqueue_command("acq stop")

def set_watermark(self, words: int) -> None:
    if words not in (128, 256, 511):
        raise ValueError("watermark must be 128, 256 or 511")
    self.enqueue_command(f"acq watermark {words}")

def request_status(self) -> None:
    self.enqueue_command("status")
```

The test-only `idle_limit` ends after that many empty reads; production passes `None` and exits only when the stop event is set.

- [ ] **Step 5: Run controller and all Qt-free tests**

Run:

```powershell
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_protocol_golden.py .\host\tests\test_sample_store.py .\host\tests\test_recorder_replay.py .\host\tests\test_transport.py .\host\tests\test_acquisition_controller.py -q
```

Expected: all listed tests pass.

- [ ] **Step 6: Commit**

```powershell
git add host/src/sensor_host/acquisition host/tests/conftest.py host/tests/test_acquisition_controller.py
git commit -m "feat: add acquisition control engine"
```

---

### Task 7: Build the PyQt application shell and theme

**Files:**
- Create: `host/src/sensor_host/presentation/__init__.py`
- Create: `host/src/sensor_host/presentation/theme.py`
- Create: `host/src/sensor_host/presentation/main_window.py`
- Create: `host/src/sensor_host/app.py`
- Create: `host/tests/test_widgets.py`

- [ ] **Step 1: Write a failing shell-state test**

```python
# host/tests/test_widgets.py
from sensor_host.presentation.main_window import MainWindow


def test_disconnected_window_disables_stream_controls(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_connected(False)

    assert window.connect_button.isEnabled()
    assert not window.disconnect_button.isEnabled()
    assert not window.pause_button.isEnabled()
    assert not window.record_button.isEnabled()
    assert window.connection_badge.text() == "DISCONNECTED"
```

- [ ] **Step 2: Run and verify failure**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_widgets.py -q`

Expected: presentation imports fail.

- [ ] **Step 3: Define design tokens and QSS**

```python
# host/src/sensor_host/presentation/theme.py
COLORS = {
    "background": "#0D1725",
    "panel": "#172538",
    "panel_alt": "#111E2E",
    "border": "#2B415A",
    "text": "#E6EDF7",
    "muted": "#8297B2",
    "cyan": "#55E2D2",
    "green": "#38D488",
    "red": "#EF5555",
    "amber": "#F0B23D",
    "blue": "#56A7FF",
}


def dark_stylesheet() -> str:
    return f"""
    QMainWindow, QWidget {{ background: {COLORS['background']}; color: {COLORS['text']}; }}
    QFrame[card="true"] {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']}; border-radius: 8px; }}
    QPushButton {{ min-height: 30px; padding: 0 12px; border: 1px solid {COLORS['border']}; border-radius: 6px; }}
    QPushButton:hover {{ border-color: {COLORS['cyan']}; }}
    QPushButton:disabled {{ color: {COLORS['muted']}; background: {COLORS['panel_alt']}; }}
    QComboBox, QLineEdit {{ min-height: 30px; border: 1px solid {COLORS['border']}; border-radius: 6px; padding: 0 8px; }}
    """
```

- [ ] **Step 4: Implement the approved shell**

`MainWindow` must expose named widgets used by tests and later composition: `device_combo`, `connect_button`, `connection_badge`, `disconnect_button`, `pause_button`, `record_button`, `watermark_combo`, and a `QTabWidget` with `LIVE MONITOR`, `DIAGNOSTICS`, `CONSOLE`.

The live tab uses a horizontal splitter with stretch factors 2:1. The left placeholder card is replaced in Task 8. The right vertical splitter contains orientation and attitude placeholders replaced in Task 9. The full-width bottom status strip remains visible.

Define signals:

```python
connect_requested = pyqtSignal(str)
disconnect_requested = pyqtSignal()
pause_toggled = pyqtSignal(bool)
record_toggled = pyqtSignal(bool)
watermark_requested = pyqtSignal(int)
```

`set_connected(False)` enforces the exact state asserted by the test. `app.py` creates `QApplication`, applies `dark_stylesheet()`, constructs `MainWindow`, shows it, and returns `app.exec()`.

- [ ] **Step 5: Run the widget test offscreen**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_widgets.py -q
```

Expected: test passes without opening a visible window.

- [ ] **Step 6: Commit**

```powershell
git add host/src/sensor_host/presentation host/src/sensor_host/app.py host/tests/test_widgets.py
git commit -m "feat: add sensor host application shell"
```

---

### Task 8: Implement the real-time vibration view

**Files:**
- Create: `host/src/sensor_host/presentation/vibration_view.py`
- Modify: `host/src/sensor_host/presentation/main_window.py`
- Modify: `host/tests/test_widgets.py`

- [ ] **Step 1: Add failing curve, units and pause tests**

```python
from sensor_host.acquisition.models import UiSnapshot
from sensor_host.presentation.vibration_view import VibrationView


def test_vibration_view_updates_three_curves_and_pause_freezes(qtbot) -> None:
    view = VibrationView()
    qtbot.addWidget(view)
    snapshot = UiSnapshot.for_test(
        time_s=[-1.0, 0.0],
        x_g=[1.0, 2.0],
        y_g=[3.0, 4.0],
        z_g=[5.0, 6.0],
    )
    view.update_snapshot(snapshot)
    assert view.x_curve.getData()[1].tolist() == [1.0, 2.0]
    assert view.plot.getAxis("bottom").labelText == "TIME"
    assert view.plot.getAxis("left").labelUnits == "g"

    view.set_paused(True)
    view.update_snapshot(UiSnapshot.for_test(time_s=[0.0], x_g=[9.0], y_g=[9.0], z_g=[9.0]))
    assert view.x_curve.getData()[1].tolist() == [1.0, 2.0]
```

Add `UiSnapshot.for_test()` as a classmethod that converts lists to float64 arrays and supplies empty/default health fields. This keeps widget tests concise without weakening production types.

- [ ] **Step 2: Run and verify failure**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_widgets.py -q`

Expected: `VibrationView` import fails.

- [ ] **Step 3: Implement the plot**

Use one `pyqtgraph.PlotWidget` with OpenGL acceleration enabled where available, antialiasing disabled for throughput, `clipToView=True`, and three curves:

```python
self.x_curve = self.plot.plot(pen=pg.mkPen("#EF5555", width=1.2), name="X")
self.y_curve = self.plot.plot(pen=pg.mkPen("#38D488", width=1.2), name="Y")
self.z_curve = self.plot.plot(pen=pg.mkPen("#56A7FF", width=1.2), name="Z")
self.plot.setLabel("bottom", "TIME", units="s")
self.plot.setLabel("left", "ACCELERATION", units="g")
self.plot.showGrid(x=True, y=True, alpha=0.18)
```

Add checkable X/Y/Z buttons, an `AUTO Y` button, and a paused badge. `update_snapshot()` calls `setData(snapshot.time_s, channel, skipFiniteCheck=True)` only when not paused.

- [ ] **Step 4: Replace the live-tab placeholder and run tests**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_widgets.py -q`

Expected: shell and vibration tests pass.

- [ ] **Step 5: Commit**

```powershell
git add host/src/sensor_host/acquisition/models.py host/src/sensor_host/presentation/vibration_view.py host/src/sensor_host/presentation/main_window.py host/tests/test_widgets.py
git commit -m "feat: plot realtime IIS3DWB vibration"
```

---

### Task 9: Implement JY61PL orientation and fallback

**Files:**
- Create: `host/src/sensor_host/presentation/orientation_view.py`
- Create: `host/tests/test_orientation.py`
- Modify: `host/src/sensor_host/presentation/main_window.py`
- Modify: `host/tests/test_widgets.py`

- [ ] **Step 1: Write failing rotation semantics tests**

```python
# host/tests/test_orientation.py
import numpy as np

from sensor_host.presentation.orientation_view import rotation_matrix_zyx, world_acceleration


def test_positive_yaw_rotates_local_x_to_world_y() -> None:
    rotation = rotation_matrix_zyx(roll_deg=0.0, pitch_deg=0.0, yaw_deg=90.0)
    assert rotation @ np.array([1.0, 0.0, 0.0]) == pytest.approx([0.0, 1.0, 0.0], abs=1e-7)


def test_acceleration_vector_rotates_with_device() -> None:
    vector = world_acceleration((1.0, 0.0, 0.0), (0.0, 0.0, 90.0))
    assert vector == pytest.approx((0.0, 1.0, 0.0), abs=1e-7)
```

Import `pytest` in the test module.

- [ ] **Step 2: Run and verify failure**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_orientation.py -q`

Expected: orientation module is absent.

- [ ] **Step 3: Implement pure ZYX math**

```python
def rotation_matrix_zyx(roll_deg: float, pitch_deg: float, yaw_deg: float) -> np.ndarray:
    roll, pitch, yaw = np.deg2rad([roll_deg, pitch_deg, yaw_deg])
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    return rz @ ry @ rx


def world_acceleration(acceleration_g, angles_deg) -> tuple[float, float, float]:
    rotation = rotation_matrix_zyx(*angles_deg)
    return tuple((rotation @ np.asarray(acceleration_g, dtype=np.float64)).tolist())
```

- [ ] **Step 4: Build the OpenGL widget with explicit fallback**

`OrientationView` first attempts to create a `pyqtgraph.opengl.GLViewWidget`, grid, colored world axes, a shallow rectangular `GLBoxItem` or mesh with a visible forward marker, and one cyan acceleration line. Convert the 3x3 rotation to a `QMatrix4x4` and call `setTransform()`; update the vector from `world_acceleration()`.

If OpenGL widget creation raises, install a fallback `QFrame` showing roll, pitch, yaw and a 2D axis glyph. Store `using_opengl: bool` and `fallback_reason: str | None`. This fallback is a supported state, not a hidden exception.

For `orientation_age_s > 0.5`, set a `STALE` badge; for no sample, show `WAITING FOR JY61PL` and identity orientation. Add compact roll/pitch/yaw, acceleration XYZ, magnitude and temperature value cards below the 3D area.

- [ ] **Step 5: Add a widget fallback test and run the suite**

```python
def test_orientation_view_can_force_fallback(qtbot) -> None:
    view = OrientationView(force_fallback=True)
    qtbot.addWidget(view)
    assert view.using_opengl is False
    assert "2D" in view.mode_label.text()
```

Run:

```powershell
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_orientation.py .\host\tests\test_widgets.py -q
```

Expected: math and forced-fallback tests pass in offscreen mode.

- [ ] **Step 6: Commit**

```powershell
git add host/src/sensor_host/presentation/orientation_view.py host/src/sensor_host/presentation/main_window.py host/tests/test_orientation.py host/tests/test_widgets.py
git commit -m "feat: render JY61PL device orientation"
```

---

### Task 10: Add diagnostics, CLI and Qt thread composition

**Files:**
- Create: `host/src/sensor_host/presentation/diagnostics_view.py`
- Create: `host/src/sensor_host/presentation/console_view.py`
- Create: `host/src/sensor_host/presentation/app_controller.py`
- Modify: `host/src/sensor_host/presentation/main_window.py`
- Modify: `host/src/sensor_host/app.py`
- Modify: `host/tests/test_widgets.py`
- Create: `host/tests/test_app_smoke.py`

- [ ] **Step 1: Add failing CLI bound and thread-shutdown tests**

```python
def test_console_bounds_transcript_and_emits_trimmed_command(qtbot) -> None:
    console = ConsoleView(max_blocks=100)
    qtbot.addWidget(console)
    with qtbot.waitSignal(console.command_submitted) as signal:
        console.command_input.setText(" status ")
        console.send_button.click()
    assert signal.args == ["status"]
    for index in range(150):
        console.append_local(f"line {index}")
    assert console.transcript.document().blockCount() <= 100


def test_app_controller_stops_worker_thread(qtbot, fake_transport_factory) -> None:
    controller = AppController(fake_transport_factory)
    controller.connect_device("FAKE")
    qtbot.waitUntil(lambda: controller.is_running, timeout=1000)
    controller.disconnect_device()
    qtbot.waitUntil(lambda: not controller.is_running, timeout=2000)
```

Add a deterministic idle transport factory to `host/tests/conftest.py`:

```python
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
    return lambda: IdleFakeTransport()
```

`AppController` calls the zero-argument factory, then calls `transport.open(device_id)` before moving the worker to its thread.

- [ ] **Step 2: Run and verify failure**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_widgets.py .\host\tests\test_app_smoke.py -q`

Expected: missing views/controller cause collection failure.

- [ ] **Step 3: Implement bounded diagnostics and console views**

`DiagnosticsView.update_snapshot()` renders every `StatusV1` field plus parser stats and acquisition health in a fixed grid; it replaces label text in place and never appends per-frame widgets.

`ConsoleView` uses a read-only `QPlainTextEdit` with `setMaximumBlockCount(max_blocks)`, a `QLineEdit`, a send button, and `command_submitted = pyqtSignal(str)`. Reject blank commands and display TX, CLI response and local error categories with fixed colors.

- [ ] **Step 4: Implement QThread lifecycle**

`AcquisitionWorker(QObject)` receives an already-open transport, store and controller. Its `run()` slot calls the Qt-free `AcquisitionController.run(stop_event)`, emits `started`, `stopped`, and `failed(str)`, and never updates widgets.

`AppController(QObject)` owns one `QThread`, one worker, one stop `threading.Event`, one store and one 33 ms `QTimer`. It exposes:

```python
snapshot_ready = pyqtSignal(object)
connection_changed = pyqtSignal(bool, str)
error_raised = pyqtSignal(str)

def connect_device(self, device_id: str) -> None: ...
def disconnect_device(self) -> None: ...
def send_command(self, command: str) -> None: ...
def set_watermark(self, words: int) -> None: ...
def set_display_paused(self, paused: bool) -> None: ...
def set_recording(self, enabled: bool, path: Path | None = None) -> None: ...
```

The timer calls `store.snapshot(window_s, max_points=5000)` and emits one immutable snapshot. On disconnect, set stop, call `thread.quit()`, wait at most three seconds, then emit a failure if the thread remains running. Never call `QThread.terminate()`.

- [ ] **Step 5: Wire the composition root**

`app.py` creates `CdcSerialTransport`, `AppController` and `MainWindow`; connects window signals to controller slots and controller snapshots to the three views. `aboutToQuit` calls `disconnect_device()`.

Refresh the device combo at startup and on an explicit refresh button. Do not automatically open the first COM port.

- [ ] **Step 6: Run all host tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests -q
```

Expected: all host unit and integration tests pass; no `QThread: Destroyed while thread is still running` warning.

- [ ] **Step 7: Commit**

```powershell
git add host/src/sensor_host/presentation host/src/sensor_host/app.py host/tests/test_widgets.py host/tests/test_app_smoke.py
git commit -m "feat: integrate diagnostics console and acquisition thread"
```

---

### Task 11: Add deterministic replay, visual baseline and performance checks

**Files:**
- Modify: `host/src/sensor_host/storage/replay.py`
- Create: `host/tools/capture_visual_baseline.py`
- Create: `host/tests/test_replay_performance.py`
- Create: `host/tests/golden/visual/manifest.json`
- Generated: `host/tests/golden/visual/dark-live-monitor.png`

- [ ] **Step 1: Write a failing 2x-stream replay test**

```python
# host/tests/test_replay_performance.py
import time

from sensor_host.protocol import StreamParser


def test_parser_replays_two_megabytes_faster_than_realtime(golden_stream: bytes) -> None:
    payload = (golden_stream * ((2_000_000 // len(golden_stream)) + 1))[:2_000_000]
    parser = StreamParser()
    started = time.perf_counter()
    for offset in range(0, len(payload), 4096):
        parser.feed(payload[offset : offset + 4096])
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0
    assert parser.stats.crc_errors == 0
```

The five-second bound is intentionally loose for CI and still far faster than the approximately ten seconds represented by 2 MB of current IIS wire traffic.

- [ ] **Step 2: Run the performance test**

Run: `& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_replay_performance.py -q`

Expected: pass. If it fails, profile parser buffer deletion and chunk handling before changing the bound.

- [ ] **Step 3: Implement deterministic fake-data screenshot capture**

`capture_visual_baseline.py` sets a 1920x1080 window, applies the dark theme, constructs a deterministic `UiSnapshot` with 2,000 points of three sine waves, a JY sample `(roll=12.4, pitch=-3.7, yaw=128.1)`, zero-error status, processes events, and calls `window.grab().save(output_path)`.

Use manifest fields:

```json
{
  "window": [1920, 1080],
  "theme": "dark",
  "screen": "live-monitor",
  "baseline": "dark-live-monitor.png",
  "review": "manual pixel review; geometry assertions remain automated"
}
```

- [ ] **Step 4: Generate and inspect the visual baseline**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe .\host\tools\capture_visual_baseline.py --output .\host\tests\golden\visual\dark-live-monitor.png
```

Expected: a readable 1920x1080 PNG with the approved dual-focus hierarchy, no clipped labels and no absolute-position display. Inspect the PNG before committing it.

- [ ] **Step 5: Commit**

```powershell
git add host/src/sensor_host/storage/replay.py host/tools/capture_visual_baseline.py host/tests/test_replay_performance.py host/tests/golden/visual
git commit -m "test: add host replay and visual baselines"
```

---

### Task 12: Write the host README and root integration guide

**Files:**
- Create: `host/README.md`
- Modify: `README.md`
- Modify: `docs/plans/2026-08-27-sensor-host-application-design.md`

- [ ] **Step 1: Write the host README in executable order**

Use these sections, in this exact order:

```markdown
# STM32 Sensor Host

PyQt6 desktop host for SDF1 acquisition over the STM32 USB CDC interface.

## Five-minute quick start
## What this does and does not do
## Prerequisites
## Setup
## Usage
## Recording and replay
## Project structure
## Configuration
## CDC hardware acceptance
## Troubleshooting
## Contributing
```

The quick start must use the cached Python executable to create `host/.venv`, install `-e '.\host[dev]'`, run tests, and launch `stm32-sensor-host`. State expected visible results after each command.

Document explicitly:

- CDC is the only current host transport.
- The CDC baud selection does not set USB wire throughput.
- The app displays orientation, not absolute position or raw nine-axis channels.
- `.sdf1` is the authoritative raw recording and `.json` is session metadata.
- CSV export is deferred until requested; no generic file manager is included.
- UART/ESP32 remains hardware-unverified.

- [ ] **Step 2: Update the firmware root README**

Add a short `PyQt 上位机` section after build/test that links `host/README.md`, includes the launch command, and states that the current merge gate is CDC end-to-end validation. Update the directory tree to include `host/`.

- [ ] **Step 3: Update design acceptance tracking**

In `docs/plans/2026-08-27-sensor-host-application-design.md`, resolve the CSV question as deferred and check only acceptance items proven by automated tests. Leave CDC hardware and sustained-run boxes unchecked until Task 13 completes.

- [ ] **Step 4: Validate documentation and links**

Run:

```powershell
git diff --check
rg -n "host/README.md|ESP32_GATEWAY_REQUIREMENTS|sensor-host-application-design" README.md docs host/README.md
```

Expected: no whitespace errors; every referenced file exists and all current-stage limitations are stated.

- [ ] **Step 5: Commit**

```powershell
git add README.md host/README.md docs/plans/2026-08-27-sensor-host-application-design.md
git commit -m "docs: add sensor host operating guide"
```

---

### Task 13: Run offline verification and CDC hardware acceptance

**Files:**
- Create: `host/tools/cdc_acceptance.py`
- Create: `host/tests/test_cdc_acceptance.py`
- Create: `host/src/sensor_host/tools/__init__.py`
- Create: `host/src/sensor_host/tools/acceptance_models.py`
- Modify after passing: `docs/ROADMAP.md`
- Modify after passing: `docs/plans/2026-08-27-sensor-host-application-design.md`

- [ ] **Step 1: Write a failing acceptance-report test**

```python
# host/tests/test_cdc_acceptance.py
from sensor_host.tools.acceptance_models import AcceptanceReport


def test_acceptance_report_requires_zero_integrity_errors() -> None:
    report = AcceptanceReport(
        duration_s=1800.0,
        bytes_received=350_000_000,
        frames=100_000,
        crc_errors=0,
        sequence_gaps=0,
        source_drop_delta=0,
        transport_drop_delta=0,
        fifo_overrun_delta=0,
        recorder_bytes=350_000_000,
        replay_frames=100_000,
    )
    assert report.passed
    assert not report.with_updates(crc_errors=1).passed
    assert not report.with_updates(replay_frames=99_999).passed
```

Place the reusable immutable model in `host/src/sensor_host/tools/acceptance_models.py`, expose it from `host/src/sensor_host/tools/__init__.py`, and implement `with_updates()` through `dataclasses.replace`:

```python
def with_updates(self, **changes) -> "AcceptanceReport":
    return dataclasses.replace(self, **changes)
```

- [ ] **Step 2: Implement the timed CDC runner**

`cdc_acceptance.py` arguments:

```text
--port COMx              required
--duration 1800          default 30 minutes
--output host/recordings/acceptance-<UTC>.sdf1
--watermark 256          allowed 128, 256, 511
--warmup 5               seconds excluded from deltas
--json-report <path>     optional explicit report path
```

The runner must:

1. Open CDC and request `status`.
2. Record baseline STATUS counters after warmup.
3. Start raw recording and parse the same chunks.
4. Request STATUS every five seconds without stopping acquisition.
5. Stop after duration, close and finalize recording.
6. Replay the file with a fresh parser.
7. Compare live and replay frame counts, CRC and sequence metrics.
8. Write a JSON report and return exit code 0 only when `AcceptanceReport.passed`.

Do not treat JY61PL absence as a stream-integrity failure; report its frame count separately because module wiring may vary.

- [ ] **Step 3: Run the complete offline gate**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests .\test\test_protocol.py -q
& .\host\.venv\Scripts\python.exe -m compileall -q .\host\src
git diff --check
```

Expected: all tests pass, compileall exits zero, and the diff check is empty.

- [ ] **Step 4: Run a five-minute CDC smoke acceptance**

Discover the STM32 CDC COM port with `python -m serial.tools.list_ports -v`, then run:

```powershell
& .\host\.venv\Scripts\python.exe .\host\tools\cdc_acceptance.py --port COMx --duration 300 --watermark 256
```

Expected: exit code 0, CRC errors 0, sequence gaps 0, source/transport/fifo deltas 0, and replay frame count equal to live frame count.

- [ ] **Step 5: Launch and visually verify the real application**

Run: `& .\host\.venv\Scripts\stm32-sensor-host.exe`

Verify:

- CDC connect/disconnect works.
- XYZ plot moves without freezing controls.
- JY model rotates when JY frames arrive; otherwise it shows a stale/waiting state.
- Pause freezes only display, not raw recording.
- `status`, stop/start and watermark controls return valid responses.
- Disconnecting USB ends the session cleanly and does not leave a running thread.

- [ ] **Step 6: Run the 30-minute merge-gate acceptance**

Run the same command with `--duration 1800`. Do not shorten this gate after a five-minute smoke pass.

Expected: the generated JSON report has `passed: true` and contains the recording path, firmware status deltas and replay comparison.

- [ ] **Step 7: Update completion evidence and commit**

Only after the report passes, check the CDC hardware acceptance items in the design document and update `docs/ROADMAP.md` with the date, duration and report summary. Do not commit large `.sdf1` recordings; commit only a small redacted JSON summary if it contains no machine-specific path.

```powershell
git add host/src/sensor_host/tools host/tools/cdc_acceptance.py host/tests/test_cdc_acceptance.py docs/ROADMAP.md docs/plans/2026-08-27-sensor-host-application-design.md
git commit -m "test: qualify CDC sensor host path"
```

---

## 2. Final Verification and Merge Gate

Run from the feature worktree:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests .\test\test_protocol.py -q
& .\host\.venv\Scripts\python.exe -m compileall -q .\host\src
cmake --build --preset Debug
cmake --build --preset Release
ctest --test-dir .\build\Debug --output-on-failure
git diff --check
git status --short --branch
```

Required evidence before merging to `master`:

- Host and firmware automated tests pass.
- Debug and Release firmware builds pass using the cached toolchain.
- Five-minute and 30-minute CDC acceptance reports pass.
- Real UI interaction and 3D/fallback behavior are visually checked.
- Recorded stream replay matches live frame and sequence metrics.
- Worktree is clean.
- Release notes state that UART/ESP32 hardware is still unverified and is governed by Stage 2B.

## 3. Plan Self-review

- Spec coverage: transport, parser, timestamped vibration, JY orientation, no absolute position, diagnostics, CLI, recording/replay, failure fallback, performance, docs and CDC hardware gate each map to an explicit task.
- Scope separation: ESP32 implementation is excluded; only its already-approved handoff dependency is referenced.
- Placeholder scan: implementation steps contain concrete file names, interfaces, test code, commands and expected outcomes; no deferred implementation placeholder is used.
- Type consistency: `StreamParser`, `RealtimeSampleStore`, `UiSnapshot`, `AcquisitionController`, `RawSessionRecorder`, `Transport`, `AppController` and `OrientationView` retain the same names and responsibilities throughout the plan.
