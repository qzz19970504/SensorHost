"""File-backed playback source feeding the existing live display pipeline."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from sensor_host.acquisition import RealtimeSampleStore
from sensor_host.protocol import Frame, MessageType, StreamParser
from sensor_host.storage.archive_library import PlaybackIndex


_TICK_MS = 33
_MAX_DISPLAY_POINTS = 5_000
_READ_CHUNK_BYTES = 262_144
_ALLOWED_SPEEDS = (0.5, 1.0, 2.0, 4.0)
_END_EPSILON_S = 1e-6


class PlaybackController(QObject):
    """Decode one archived SDF1 file in time order at a selectable speed."""

    snapshot_ready = pyqtSignal(object)
    state_changed = pyqtSignal(bool, float, float)
    playback_stopped = pyqtSignal()

    def __init__(
        self,
        window_seconds_provider: Callable[[], float],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._window_seconds_provider = window_seconds_provider
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._parser = StreamParser()
        self._store = RealtimeSampleStore()
        self._stream: BinaryIO | None = None
        self._index: PlaybackIndex | None = None
        self._pending_frames: deque[Frame] = deque()
        self._playing = False
        self._eof = False
        self._playhead_s = 0.0
        self._speed = 1.0
        self._last_tick_s = 0.0

    @property
    def is_loaded(self) -> bool:
        return self._index is not None

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def duration_s(self) -> float:
        return 0.0 if self._index is None else self._index.duration_s

    @property
    def playhead_s(self) -> float:
        return self._playhead_s

    def load(self, path: Path, index: PlaybackIndex) -> None:
        """Attach one indexed archive file and reset the playhead to zero."""
        self.pause()
        if self._stream is not None:
            self._stream.close()
        self._stream = Path(path).open("rb")
        self._index = index
        self._store = RealtimeSampleStore()
        self._playhead_s = 0.0
        self._restart_decoder(0.0)
        self._emit_state()

    def play(self) -> None:
        """Resume from the playhead, restarting when parked at the end."""
        if self._index is None:
            return
        if self._playhead_s >= self.duration_s - _END_EPSILON_S:
            self.seek(0.0)
        if self._playing:
            return
        self._playing = True
        self._last_tick_s = time.monotonic()
        self._timer.start()
        self._emit_state()

    def pause(self) -> None:
        """Freeze the playhead without discarding decoded history."""
        if not self._playing:
            return
        self._playing = False
        self._timer.stop()
        self._emit_state()

    def stop(self) -> None:
        """Leave playback mode and discard all decoded history."""
        self._playing = False
        self._timer.stop()
        if self._index is not None:
            self._playhead_s = 0.0
            self._store.clear_samples()
            self._restart_decoder(0.0)
        self._emit_state()
        self.playback_stopped.emit()

    def seek(self, time_s: float) -> None:
        """Jump the playhead, refilling the display window before it."""
        if self._index is None:
            return
        target = min(max(0.0, float(time_s)), self.duration_s)
        self._playhead_s = target
        self._store.clear_samples()
        window_s = self._window_seconds()
        self._restart_decoder(max(0.0, target - window_s))
        self._fill_until(target)
        self._emit_snapshot()
        self._emit_state()

    def set_speed(self, speed: float) -> None:
        if speed not in _ALLOWED_SPEEDS:
            raise ValueError("speed must be one of 0.5, 1, 2 or 4")
        self._speed = float(speed)

    def close(self) -> None:
        """Release the archive file handle."""
        self.pause()
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        self._index = None

    def _tick(self) -> None:
        index = self._index
        if index is None:
            self.pause()
            return
        now_s = time.monotonic()
        elapsed_s = max(0.0, now_s - self._last_tick_s)
        self._last_tick_s = now_s
        target = self._playhead_s + elapsed_s * self._speed
        reached_end = target >= index.duration_s - _END_EPSILON_S
        target = min(target, index.duration_s)
        self._playhead_s = target
        self._fill_until(target)
        self._emit_snapshot()
        if reached_end and self._eof and not self._pending_frames:
            self._playing = False
            self._timer.stop()
        self._emit_state()

    def _fill_until(self, time_s: float) -> None:
        cutoff_us = self._cutoff_us(time_s)
        while True:
            while (
                self._pending_frames
                and self._pending_frames[0].timestamp_us <= cutoff_us
            ):
                self._apply_frame(self._pending_frames.popleft())
            if self._pending_frames or self._eof:
                return
            chunk = self._stream.read(_READ_CHUNK_BYTES) if self._stream else None
            if not chunk:
                self._eof = True
                continue
            for frame in self._parser.feed(chunk):
                if frame.message_type in (
                    MessageType.IIS3DWB_FIFO,
                    MessageType.JY61PL_SAMPLE,
                ):
                    self._pending_frames.append(frame)

    def _apply_frame(self, frame: Frame) -> None:
        if frame.message_type is MessageType.IIS3DWB_FIFO:
            if frame.iis_ts_us is not None:
                self._store.append_iis_arrays(frame.iis_ts_us, frame.iis_accel_g)
            else:
                self._store.append_iis(frame.iis_samples or ())
            return
        if frame.message_type is MessageType.JY61PL_SAMPLE and frame.jy61pl is not None:
            self._store.update_jy(frame.jy61pl, time.monotonic())

    def _restart_decoder(self, time_s: float) -> None:
        index = self._index
        stream = self._stream
        if index is None or stream is None:
            return
        stream.seek(index.offset_for_time(time_s))
        self._parser.reset_session()
        self._pending_frames.clear()
        self._eof = False

    def _cutoff_us(self, time_s: float) -> float:
        index = self._index
        base_us = 0.0 if index is None else index.first_timestamp_us
        return base_us + time_s * 1_000_000.0

    def _window_seconds(self) -> float:
        try:
            window_s = float(self._window_seconds_provider())
        except (TypeError, ValueError):
            return 10.0
        return window_s if window_s > 0.0 else 10.0

    def _emit_snapshot(self) -> None:
        self.snapshot_ready.emit(
            self._store.snapshot(self._window_seconds(), _MAX_DISPLAY_POINTS)
        )

    def _emit_state(self) -> None:
        self.state_changed.emit(self._playing, self._playhead_s, self.duration_s)
