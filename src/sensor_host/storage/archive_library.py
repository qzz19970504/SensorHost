"""Local export library scan and playback index for raw SDF1 archives."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from sensor_host.storage.paths import data_root


MAGIC = b"SDF1"
VERSION_V1 = 1
VERSION_V2 = 2
HEADER_SIZE = 28
DATA_HEADER_SIZE = 44
CRC_SIZE = 4
MAX_PAYLOAD_SIZE = 3577
IIS_WORD_SIZE = 7
MESSAGE_IIS3DWB_FIFO = 1
MESSAGE_JY61PL_SAMPLE = 2

_HEADER_FIELDS = struct.Struct("<HHHIQHH")


@dataclass(frozen=True)
class ExportEntry:
    """Describe one exported archive file and its sidecar metadata."""

    path: Path
    name: str
    started_utc: str
    ended_utc: str
    bytes_written: int
    status: str
    alias: str
    uuid: str


@dataclass(frozen=True)
class PlaybackIndex:
    """Map playback time to file offsets without holding decoded samples."""

    path: Path
    offsets: NDArray[np.int64]
    timestamps_us: NDArray[np.float64]
    cum_samples: NDArray[np.int64]
    kinds: NDArray[np.int8]
    total_samples: int
    first_timestamp_us: float
    last_timestamp_us: float

    @property
    def duration_s(self) -> float:
        """Return the IIS sample span in seconds."""
        if self.last_timestamp_us <= self.first_timestamp_us:
            return 0.0
        return (self.last_timestamp_us - self.first_timestamp_us) / 1_000_000.0

    @property
    def sample_rate_hz(self) -> float:
        duration_s = self.duration_s
        if duration_s <= 0.0 or self.total_samples < 2:
            return 0.0
        return self.total_samples / duration_s

    def offset_for_time(self, time_s: float) -> int:
        """Return the file offset of the last frame at or before one time."""
        if self.offsets.size == 0:
            return 0
        target_us = self.first_timestamp_us + max(0.0, time_s) * 1_000_000.0
        index = int(np.searchsorted(self.timestamps_us, target_us, side="right")) - 1
        return int(self.offsets[max(0, index)])


def scan_exports(root: Path | None = None) -> list[ExportEntry]:
    """Return exported archive files newest first, sidecar metadata merged."""
    export_root = Path(root) if root is not None else data_root() / "exports"
    entries: list[ExportEntry] = []
    if not export_root.exists():
        return entries
    for path in export_root.rglob("*.sdf1"):
        if not path.is_file():
            continue
        entries.append(_entry_for(path))
    entries.sort(key=lambda entry: (entry.started_utc, entry.name), reverse=True)
    return entries


def _entry_for(path: Path) -> ExportEntry:
    metadata: dict[str, object] = {}
    sidecar = path.with_suffix(".json")
    if sidecar.exists():
        try:
            loaded = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = {}
        if isinstance(loaded, dict):
            metadata = loaded
    try:
        stat = path.stat()
        size = stat.st_size
        modified = stat.st_mtime
    except OSError:
        size = 0
        modified = 0.0
    started = str(metadata.get("started_utc") or "")
    if not started:
        started = datetime.fromtimestamp(modified, timezone.utc).isoformat()
    return ExportEntry(
        path=path,
        name=path.name,
        started_utc=started,
        ended_utc=str(metadata.get("ended_utc") or ""),
        bytes_written=int(metadata.get("bytes_written") or size),
        status=str(metadata.get("status") or "unknown"),
        alias=str(metadata.get("alias") or ""),
        uuid=str(metadata.get("uuid") or ""),
    )


def build_playback_index(path: Path) -> PlaybackIndex:
    """Scan frame headers once to build a seekable time index.

    The scan trusts magic/header/payload sizes but skips CRC validation;
    playback decoding still runs every frame through the full parser.
    """
    offsets: list[int] = []
    timestamps: list[float] = []
    cum_samples: list[int] = []
    kinds: list[int] = []
    total_samples = 0
    first_iis_us: float | None = None
    last_iis_us: float | None = None

    with Path(path).open("rb") as stream:
        while True:
            offset = stream.tell()
            header = stream.read(DATA_HEADER_SIZE)
            if not header:
                break
            if len(header) < HEADER_SIZE or header[:4] != MAGIC:
                break
            version = header[4]
            message_type = header[5]
            if version == VERSION_V1 and len(header) < HEADER_SIZE:
                break
            if version not in (VERSION_V1, VERSION_V2):
                break
            (
                _flags,
                header_size,
                payload_size,
                _sequence,
                timestamp_us,
                _item_count,
                _reserved,
            ) = _HEADER_FIELDS.unpack_from(header, 6)
            expected_header = (
                DATA_HEADER_SIZE if version == VERSION_V2 else HEADER_SIZE
            )
            if header_size != expected_header or payload_size > MAX_PAYLOAD_SIZE:
                break
            frame_size = header_size + payload_size + CRC_SIZE
            if message_type == MESSAGE_IIS3DWB_FIFO:
                stream.seek(offset + header_size)
                payload = stream.read(payload_size)
                if len(payload) != payload_size:
                    break
                sample_count = sum(
                    1
                    for word_start in range(0, payload_size, IIS_WORD_SIZE)
                    if payload[word_start] >> 3 == 2
                )
                total_samples += sample_count
                if first_iis_us is None:
                    first_iis_us = float(timestamp_us)
                last_iis_us = float(timestamp_us)
                kind = 1
            elif message_type == MESSAGE_JY61PL_SAMPLE:
                kind = 2
            else:
                kind = 0
            offsets.append(offset)
            timestamps.append(float(timestamp_us))
            cum_samples.append(total_samples)
            kinds.append(kind)
            stream.seek(offset + frame_size)

    return PlaybackIndex(
        path=Path(path),
        offsets=np.asarray(offsets, dtype=np.int64),
        timestamps_us=np.asarray(timestamps, dtype=np.float64),
        cum_samples=np.asarray(cum_samples, dtype=np.int64),
        kinds=np.asarray(kinds, dtype=np.int8),
        total_samples=total_samples,
        first_timestamp_us=first_iis_us if first_iis_us is not None else 0.0,
        last_timestamp_us=last_iis_us if last_iis_us is not None else 0.0,
    )
