"""Streaming decoder for the firmware SDF1 protocol."""

from __future__ import annotations

import struct
import uuid
import zlib
from dataclasses import dataclass
from enum import IntEnum


MAGIC = b"SDF1"
VERSION = 1
HEADER_SIZE = 28
DATA_VERSION = 2
DATA_HEADER_SIZE = 44
MAX_HEADER_SIZE = 256
CRC_SIZE = 4
MAX_PAYLOAD_SIZE = 3577
IIS_WORD_SIZE = 7
IIS_TIMESTAMP_TICK_US = 25.0
IIS_SAMPLE_PERIOD_US = 37.5

_HEADER = struct.Struct("<4sBBHHHIQHH")
_STATUS = struct.Struct("<BBBBHH9I5H2xQ")


class MessageType(IntEnum):
    IIS3DWB_FIFO = 0x01
    JY61PL_SAMPLE = 0x02
    STATUS = 0x03
    CLI_RESPONSE = 0x04


@dataclass
class ParserStats:
    frames: int = 0
    bytes_discarded: int = 0
    crc_errors: int = 0
    header_errors: int = 0
    unknown_versions: int = 0
    length_errors: int = 0
    unknown_types: int = 0
    payload_errors: int = 0
    sequence_gaps: int = 0


@dataclass(frozen=True)
class Jy61plSample:
    raw: tuple[int, int, int, int, int, int, int]
    acceleration_g: tuple[float, float, float]
    temperature_c: float
    angles_deg: tuple[float, float, float]


@dataclass(frozen=True)
class StatusV1:
    status_version: int
    active_transport: int
    pending_transport: int
    acquisition_state: int
    watermark_words: int
    free_data_buffers: int
    uart_credit_bytes: int
    data_queue_peak: int
    fifo_overruns: int
    source_drops: int
    transport_drops: int
    spi_dma_errors: int
    uart_dma_errors: int
    cdc_errors: int
    command_errors: int
    iis_stack_high_water_words: int
    transport_stack_high_water_words: int
    control_stack_high_water_words: int
    jy61pl_stack_high_water_words: int
    led_stack_high_water_words: int
    uptime_us: int


@dataclass(frozen=True)
class IisFifoWord:
    raw_tag: int
    sensor_tag: int
    tag_counter: int
    tag_parity: int
    acceleration_raw: tuple[int, int, int] | None = None
    temperature_raw: int | None = None
    timestamp_ticks: int | None = None
    raw_data: bytes = b""


@dataclass(frozen=True)
class IisSample:
    timestamp_us: float
    acceleration_raw: tuple[int, int, int]
    acceleration_g: tuple[float, float, float]


@dataclass(frozen=True)
class Frame:
    message_type: MessageType
    flags: int
    sequence: int
    timestamp_us: int
    item_count: int
    payload: bytes
    device_uuid: uuid.UUID | None = None
    iis_words: tuple[IisFifoWord, ...] | None = None
    iis_samples: tuple[IisSample, ...] | None = None
    jy61pl: Jy61plSample | None = None
    status: StatusV1 | None = None
    cli_text: str | None = None

    @property
    def archive_export(self) -> bool:
        return bool(self.flags & 0x8000)


def decode_iis_words(payload: bytes) -> tuple[IisFifoWord, ...]:
    if len(payload) % IIS_WORD_SIZE:
        raise ValueError("IIS FIFO payload is not aligned to seven-byte words")
    words: list[IisFifoWord] = []
    for offset in range(0, len(payload), IIS_WORD_SIZE):
        raw_tag = payload[offset]
        data = payload[offset + 1 : offset + IIS_WORD_SIZE]
        sensor_tag = raw_tag >> 3
        acceleration = None
        temperature = None
        timestamp = None
        if sensor_tag == 2:
            acceleration = struct.unpack("<hhh", data)
        elif sensor_tag == 3:
            temperature = struct.unpack_from("<h", data)[0]
        elif sensor_tag == 4:
            timestamp = struct.unpack_from("<I", data)[0]
        words.append(
            IisFifoWord(
                raw_tag=raw_tag,
                sensor_tag=sensor_tag,
                tag_counter=(raw_tag >> 1) & 0x03,
                tag_parity=raw_tag & 0x01,
                acceleration_raw=acceleration,
                temperature_raw=temperature,
                timestamp_ticks=timestamp,
                raw_data=data,
            )
        )
    return tuple(words)


class IisTimestampReconstructor:
    """Extend sensor timestamp tags and assign times to acceleration words."""

    def __init__(self) -> None:
        self._last_ticks: int | None = None
        self._tick_epoch = 0
        self._next_sample_us: float | None = None
        self._sensor_to_mcu_offset_us: float | None = None

    def _extend_ticks(self, ticks: int) -> int:
        if (
            self._last_ticks is not None
            and ticks < self._last_ticks
            and self._last_ticks - ticks > 0x80000000
        ):
            self._tick_epoch += 1 << 32
        self._last_ticks = ticks
        return self._tick_epoch + ticks

    @staticmethod
    def _make_sample(raw: tuple[int, int, int], timestamp_us: float) -> IisSample:
        return IisSample(
            timestamp_us=timestamp_us,
            acceleration_raw=raw,
            acceleration_g=tuple(value * 0.000061 for value in raw),
        )

    def process(
        self, words: tuple[IisFifoWord, ...], frame_timestamp_us: int
    ) -> tuple[IisSample, ...]:
        samples: list[IisSample] = []
        pending: list[tuple[int, int, int]] = []
        sensor_times: dict[int, float] = {}

        for index, word in enumerate(words):
            if word.timestamp_ticks is not None:
                sensor_times[index] = (
                    self._extend_ticks(word.timestamp_ticks)
                    * IIS_TIMESTAMP_TICK_US
                )

        if sensor_times:
            anchor_index = next(reversed(sensor_times))
            accelerations_after_anchor = sum(
                word.acceleration_raw is not None
                for word in words[anchor_index + 1 :]
            )
            anchor_mcu_us = frame_timestamp_us - max(
                accelerations_after_anchor - 1, 0
            ) * IIS_SAMPLE_PERIOD_US
            self._sensor_to_mcu_offset_us = (
                anchor_mcu_us - sensor_times[anchor_index]
            )

        for index, word in enumerate(words):
            if word.acceleration_raw is not None:
                if self._next_sample_us is None:
                    pending.append(word.acceleration_raw)
                else:
                    samples.append(
                        self._make_sample(word.acceleration_raw, self._next_sample_us)
                    )
                    self._next_sample_us += IIS_SAMPLE_PERIOD_US
            elif word.timestamp_ticks is not None:
                sensor_timestamp_us = sensor_times[index]
                timestamp_us = sensor_timestamp_us
                if self._sensor_to_mcu_offset_us is not None:
                    timestamp_us += self._sensor_to_mcu_offset_us
                if pending:
                    first_time = timestamp_us - len(pending) * IIS_SAMPLE_PERIOD_US
                    samples.extend(
                        self._make_sample(raw, first_time + index * IIS_SAMPLE_PERIOD_US)
                        for index, raw in enumerate(pending)
                    )
                    pending.clear()
                self._next_sample_us = timestamp_us

        if pending:
            first_time = frame_timestamp_us - (
                len(pending) - 1
            ) * IIS_SAMPLE_PERIOD_US
            samples.extend(
                self._make_sample(raw, first_time + index * IIS_SAMPLE_PERIOD_US)
                for index, raw in enumerate(pending)
            )
            self._next_sample_us = frame_timestamp_us + IIS_SAMPLE_PERIOD_US
        return tuple(samples)


def _decode_jy61pl(payload: bytes) -> Jy61plSample:
    raw = struct.unpack("<7h", payload)
    return Jy61plSample(
        raw=raw,
        acceleration_g=tuple(value * 16.0 / 32768.0 for value in raw[:3]),
        temperature_c=raw[3] / 100.0,
        angles_deg=tuple(value * 180.0 / 32768.0 for value in raw[4:]),
    )


def _decode_status(payload: bytes) -> StatusV1:
    values = _STATUS.unpack(payload)
    return StatusV1(*values)


class StreamParser:
    def __init__(self, decode_sensor_payload: bool = True) -> None:
        self.stats = ParserStats()
        self._buffer = bytearray()
        self._last_sequence: int | None = None
        self._iis_time = IisTimestampReconstructor()
        self._decode_sensor_payload = decode_sensor_payload

    @property
    def buffered_bytes(self) -> int:
        """Return the number of undecoded bytes retained for the next feed."""
        return len(self._buffer)

    @property
    def last_sequence(self) -> int | None:
        """Return the last CRC-valid global sequence observed in this session."""
        return self._last_sequence

    def reset_session(self) -> None:
        """Clear buffered bytes, metrics, sequence state, and IIS timestamp state."""
        self.stats = ParserStats()
        self._buffer.clear()
        self._last_sequence = None
        self._iis_time = IisTimestampReconstructor()

    def _discard_until_magic(self) -> bool:
        index = self._buffer.find(MAGIC)
        if index >= 0:
            if index:
                del self._buffer[:index]
                self.stats.bytes_discarded += index
            return True
        keep = min(len(self._buffer), len(MAGIC) - 1)
        discarded = len(self._buffer) - keep
        if discarded:
            del self._buffer[:discarded]
            self.stats.bytes_discarded += discarded
        return False

    def _record_sequence(self, sequence: int) -> None:
        if self._last_sequence is not None:
            expected = (self._last_sequence + 1) & 0xFFFFFFFF
            gap = (sequence - expected) & 0xFFFFFFFF
            if gap < 0x80000000:
                self.stats.sequence_gaps += gap
        self._last_sequence = sequence

    def feed(self, data: bytes | bytearray | memoryview) -> list[Frame]:
        self._buffer.extend(data)
        frames: list[Frame] = []
        while True:
            if not self._discard_until_magic() or len(self._buffer) < HEADER_SIZE:
                break
            (
                _magic,
                version,
                message_type_value,
                flags,
                header_size,
                payload_size,
                sequence,
                timestamp_us,
                item_count,
                _reserved,
            ) = _HEADER.unpack_from(self._buffer)
            if (header_size < HEADER_SIZE) or (header_size > MAX_HEADER_SIZE):
                del self._buffer[0]
                self.stats.header_errors += 1
                self.stats.bytes_discarded += 1
                continue
            if version == VERSION and header_size != HEADER_SIZE:
                del self._buffer[0]
                self.stats.header_errors += 1
                self.stats.bytes_discarded += 1
                continue
            if version == DATA_VERSION and header_size != DATA_HEADER_SIZE:
                del self._buffer[0]
                self.stats.header_errors += 1
                self.stats.bytes_discarded += 1
                continue
            if payload_size > MAX_PAYLOAD_SIZE:
                del self._buffer[0]
                self.stats.length_errors += 1
                self.stats.bytes_discarded += 1
                continue
            frame_size = header_size + payload_size + CRC_SIZE
            if len(self._buffer) < frame_size:
                break
            candidate = bytes(self._buffer[:frame_size])
            expected_crc = struct.unpack_from("<I", candidate, frame_size - CRC_SIZE)[0]
            actual_crc = zlib.crc32(candidate[:-CRC_SIZE]) & 0xFFFFFFFF
            if actual_crc != expected_crc:
                del self._buffer[0]
                self.stats.crc_errors += 1
                self.stats.bytes_discarded += 1
                continue
            del self._buffer[:frame_size]
            if version not in (VERSION, DATA_VERSION):
                self.stats.unknown_versions += 1
                continue
            try:
                message_type = MessageType(message_type_value)
            except ValueError:
                self.stats.unknown_types += 1
                continue
            if version == DATA_VERSION and message_type not in (
                MessageType.IIS3DWB_FIFO,
                MessageType.JY61PL_SAMPLE,
            ):
                self.stats.header_errors += 1
                continue
            payload = candidate[header_size:-CRC_SIZE]
            device_uuid = (
                uuid.UUID(bytes=candidate[HEADER_SIZE:DATA_HEADER_SIZE])
                if version == DATA_VERSION
                else None
            )
            frame = self._decode_frame(
                message_type,
                flags,
                sequence,
                timestamp_us,
                item_count,
                payload,
                device_uuid,
            )
            if frame is not None:
                if message_type in (
                    MessageType.IIS3DWB_FIFO,
                    MessageType.JY61PL_SAMPLE,
                ):
                    self._record_sequence(sequence)
                frames.append(frame)
                self.stats.frames += 1
        return frames

    def _decode_frame(
        self,
        message_type: MessageType,
        flags: int,
        sequence: int,
        timestamp_us: int,
        item_count: int,
        payload: bytes,
        device_uuid: uuid.UUID | None,
    ) -> Frame | None:
        common = dict(
            message_type=message_type,
            flags=flags,
            sequence=sequence,
            timestamp_us=timestamp_us,
            item_count=item_count,
            payload=payload,
            device_uuid=device_uuid,
        )
        if message_type is MessageType.IIS3DWB_FIFO:
            if len(payload) != item_count * IIS_WORD_SIZE:
                self.stats.payload_errors += 1
                return None
            if not self._decode_sensor_payload:
                return Frame(**common)
            words = decode_iis_words(payload)
            samples = self._iis_time.process(words, timestamp_us)
            return Frame(**common, iis_words=words, iis_samples=samples)
        if message_type is MessageType.JY61PL_SAMPLE:
            if len(payload) != 14 or item_count != 1:
                self.stats.payload_errors += 1
                return None
            return Frame(**common, jy61pl=_decode_jy61pl(payload))
        if message_type is MessageType.STATUS:
            if len(payload) != 64 or item_count != 1:
                self.stats.payload_errors += 1
                return None
            return Frame(**common, status=_decode_status(payload))
        return Frame(**common, cli_text=payload.decode("utf-8", errors="replace"))
