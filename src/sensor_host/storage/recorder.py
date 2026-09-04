"""Bounded asynchronous recording of the unchanged incoming SDF1 byte stream."""

from __future__ import annotations

import json
import os
import queue
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import BinaryIO


_DEFAULT_QUEUE_CAPACITY_BYTES = 4 * 1024 * 1024
_WRITER_JOIN_TIMEOUT_SECONDS = 5.0
_QUEUE_CAPACITY_ERROR = "recording queue capacity exceeded"


@dataclass(frozen=True)
class RecordingSummary:
    """Summarize one finalized raw recording session."""

    path: Path
    bytes_written: int
    started_utc: str
    ended_utc: str
    failure: str | None


class RawSessionRecorder:
    """Write copied input chunks on a worker thread with bounded queue bytes."""

    def __init__(
        self,
        queue_capacity_bytes: int = _DEFAULT_QUEUE_CAPACITY_BYTES,
    ) -> None:
        if queue_capacity_bytes <= 0:
            raise ValueError("queue_capacity_bytes must be positive")
        self._queue_capacity_bytes = queue_capacity_bytes
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._lock = Lock()
        self._queued_bytes = 0
        self._bytes_written = 0
        self._failure: str | None = None
        self._is_active = False
        self._path: Path | None = None
        self._metadata: dict[str, object] = {}
        self._started_utc = ""
        self._stream: BinaryIO | None = None
        self._writer_thread: Thread | None = None

    @property
    def failure(self) -> str | None:
        """Return the first recording failure, if one has occurred."""
        with self._lock:
            return self._failure

    def start(self, path: Path, metadata: dict[str, object]) -> None:
        """Open a new recording and start its writer thread."""
        with self._lock:
            if self._is_active:
                raise RuntimeError("recording is already active")
            self._queued_bytes = 0
            self._bytes_written = 0
            self._failure = None
            self._path = Path(path)
            self._metadata = dict(metadata)
            self._started_utc = self._utc_now()
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._stream = self._path.open("wb")
            self._is_active = True
            self._writer_thread = Thread(
                target=self._writer_loop,
                name="sdf1-recorder",
                daemon=True,
            )
            self._writer_thread.start()

    def submit(self, chunk: bytes | bytearray | memoryview) -> bool:
        """Queue one copied chunk without blocking or exceeding byte capacity."""
        copied_chunk = bytes(chunk)
        if not copied_chunk:
            return True
        with self._lock:
            if not self._is_active:
                raise RuntimeError("recording is not active")
            if self._failure is not None:
                return False
            if self._queued_bytes + len(copied_chunk) > self._queue_capacity_bytes:
                self._failure = _QUEUE_CAPACITY_ERROR
                return False
            self._queued_bytes += len(copied_chunk)
        self._queue.put_nowait(copied_chunk)
        return True

    def update_metadata(self, values: dict[str, object]) -> None:
        """Merge session metadata before finalization without touching stream bytes."""
        with self._lock:
            if not self._is_active:
                raise RuntimeError("recording is not active")
            self._metadata.update(values)

    def stop(self) -> RecordingSummary:
        """Drain queued chunks, finalize metadata, and return a session summary."""
        with self._lock:
            if not self._is_active:
                raise RuntimeError("recording is not active")
            writer_thread = self._writer_thread
            recording_path = self._path
        if writer_thread is None or recording_path is None:
            raise RuntimeError("recording state is incomplete")

        self._queue.put_nowait(None)
        writer_thread.join(timeout=_WRITER_JOIN_TIMEOUT_SECONDS)
        if writer_thread.is_alive():
            raise RuntimeError("recording writer did not stop within five seconds")

        ended_utc = self._utc_now()
        with self._lock:
            self._is_active = False
            summary = RecordingSummary(
                path=recording_path,
                bytes_written=self._bytes_written,
                started_utc=self._started_utc,
                ended_utc=ended_utc,
                failure=self._failure,
            )
            self._writer_thread = None
            self._stream = None
        self._write_metadata(summary)
        return summary

    def _writer_loop(self) -> None:
        stream = self._stream
        if stream is None:
            return
        try:
            while True:
                chunk = self._queue.get()
                if chunk is None:
                    break
                stream.write(chunk)
                with self._lock:
                    self._queued_bytes -= len(chunk)
                    self._bytes_written += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        except OSError as error:
            with self._lock:
                if self._failure is None:
                    self._failure = f"recording write failed: {error}"
        finally:
            stream.close()

    def _write_metadata(self, summary: RecordingSummary) -> None:
        metadata_path = summary.path.with_suffix(".json")
        temporary_path = metadata_path.with_suffix(".json.tmp")
        document = dict(self._metadata)
        document.update(
            {
                "started_utc": summary.started_utc,
                "ended_utc": summary.ended_utc,
                "bytes_written": summary.bytes_written,
                "failure": summary.failure,
            }
        )
        temporary_path.write_text(
            json.dumps(document, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary_path.replace(metadata_path)

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
