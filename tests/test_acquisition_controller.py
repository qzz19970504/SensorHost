from threading import Event, Thread
import struct
import uuid
import zlib

import pytest

from sensor_host.acquisition import (
    AcquisitionController,
    DeviceIdentityError,
    RealtimeSampleStore,
)
from sensor_host.protocol import MessageType, StreamParser


def encode_frame(
    message_type: MessageType,
    payload: bytes,
    *,
    flags: int = 0,
    device_uuid: uuid.UUID | None = None,
) -> bytes:
    version = 2 if device_uuid is not None else 1
    header_size = 44 if device_uuid is not None else 28
    item_count = 1
    header = struct.pack(
        "<4sBBHHHIQHH",
        b"SDF1",
        version,
        int(message_type),
        flags,
        header_size,
        len(payload),
        1,
        100,
        item_count,
        0,
    )
    if device_uuid is not None:
        header += device_uuid.bytes
    content = header + payload
    return content + struct.pack("<I", zlib.crc32(content) & 0xFFFFFFFF)


class FakeTransport:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)
        self.commands: list[bytes] = []
        self.is_closed = False

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        try:
            return next(self._chunks)
        except StopIteration:
            return b""

    def write_control(self, command: bytes) -> None:
        self.commands.append(command)

    def close(self) -> None:
        self.is_closed = True


def test_engine_parses_golden_updates_store_and_serializes_commands(
    golden_stream: bytes,
) -> None:
    transport = FakeTransport([golden_stream])
    store = RealtimeSampleStore()
    stop_event = Event()
    controller = AcquisitionController(transport, store)
    controller.enqueue_command("status")

    controller.run(stop_event, idle_limit=2)

    assert transport.commands == [b"status"]
    assert store.snapshot(10.0, 100).parser_stats.frames == 4
    assert controller.health.bytes_received == len(golden_stream)
    assert controller.health.frames_received == 4
    assert transport.is_closed is True


@pytest.mark.parametrize("watermark", [0, 127, 129, 512])
def test_watermark_rejects_values_not_supported_by_firmware(
    watermark: int,
) -> None:
    controller = AcquisitionController(FakeTransport([]), RealtimeSampleStore())

    with pytest.raises(ValueError, match="128, 256 or 511"):
        controller.set_watermark(watermark)


def test_start_and_stop_use_official_at_commands() -> None:
    transport = FakeTransport([])
    controller = AcquisitionController(transport, RealtimeSampleStore())
    controller.start_acquisition()
    controller.stop_acquisition()

    controller._send_pending_commands()

    assert transport.commands == [b"AT+START", b"AT+STOP"]


def test_livestream_query_and_normalized_target_selection() -> None:
    transport = FakeTransport([])
    controller = AcquisitionController(transport, RealtimeSampleStore())
    controller.request_livestream()
    controller.set_livestream("uart")
    controller.set_livestream("CDC")

    controller._send_pending_commands()

    assert transport.commands == [
        b"AT+LIVESTREAM?",
        b"AT+LIVESTREAM=UART",
        b"AT+LIVESTREAM=CDC",
    ]


def test_engine_structures_control_state_and_reports_identity() -> None:
    reply = (
        "+STATE:IDLE\r\n"
        "+UUID:550e8400-e29b-41d4-a716-446655440000,SOURCE=DERIVED\r\n"
        "+LIVE:TARGET=UART,DROPS_IIS=1,DROPS_JY=2,"
        "LAST_ROUTED_SEQUENCE=3,LAST_COMPLETED_SEQUENCE=4\r\nOK\r\n"
    ).encode()
    transport = FakeTransport([encode_frame(MessageType.CLI_RESPONSE, reply)])
    store = RealtimeSampleStore()
    controller = AcquisitionController(transport, store)

    controller.run(Event(), idle_limit=1)

    snapshot = store.snapshot(10.0, 100)
    assert snapshot.firmware_control_state is not None
    assert snapshot.firmware_control_state.livestream_target == "UART"
    assert controller.drain_identity_updates() == [
        uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    ]


class RecordingArchiveSink:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def submit(self, chunk: bytes) -> bool:
        self.chunks.append(chunk)
        return True


class RecordingSink(RecordingArchiveSink):
    failure = None


class BlockingRecordingSink(RecordingSink):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def submit(self, chunk: bytes) -> bool:
        self.entered.set()
        self.release.wait(timeout=1.0)
        return super().submit(chunk)


def test_archive_frames_are_saved_without_entering_live_store() -> None:
    device_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    archive_frame = encode_frame(
        MessageType.JY61PL_SAMPLE,
        bytes(14),
        flags=0x8000,
        device_uuid=device_uuid,
    )
    transport = FakeTransport([archive_frame])
    store = RealtimeSampleStore()
    archive_sink = RecordingArchiveSink()
    controller = AcquisitionController(transport, store)
    controller.set_archive_recorder(archive_sink)

    controller.run(Event(), idle_limit=1)

    snapshot = store.snapshot(10.0, 100)
    assert snapshot.orientation is None
    assert archive_sink.chunks == [archive_frame]


def test_deferred_recording_flushes_identity_frame_to_attached_recorder() -> None:
    device_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    first_frame = encode_frame(
        MessageType.JY61PL_SAMPLE,
        bytes(14),
        device_uuid=device_uuid,
    )
    controller = AcquisitionController(FakeTransport([first_frame]), RealtimeSampleStore())
    controller.defer_recording_until_identity()

    controller.run(Event(), idle_limit=1)
    recorder = RecordingSink()
    controller.set_recorder(recorder)  # type: ignore[arg-type]

    assert recorder.chunks == [first_frame]


def test_detaching_recorder_waits_for_inflight_frame_submission() -> None:
    frame_bytes = encode_frame(MessageType.JY61PL_SAMPLE, bytes(14))
    frame = StreamParser().feed(frame_bytes)[0]
    controller = AcquisitionController(FakeTransport([]), RealtimeSampleStore())
    recorder = BlockingRecordingSink()
    controller.set_recorder(recorder)  # type: ignore[arg-type]
    submit_thread = Thread(target=controller._handle_frame, args=(frame,))
    submit_thread.start()
    assert recorder.entered.wait(timeout=1.0)

    detach_thread = Thread(target=controller.set_recorder, args=(None,))
    detach_thread.start()
    assert detach_thread.is_alive()
    recorder.release.set()
    submit_thread.join(timeout=1.0)
    detach_thread.join(timeout=1.0)

    assert recorder.chunks == [frame_bytes]
    assert not submit_thread.is_alive()
    assert not detach_thread.is_alive()


def test_connection_rejects_a_second_sensor_uuid() -> None:
    first_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    second_uuid = uuid.UUID("00112233-4455-6677-8899-aabbccddeeff")
    stream = (
        encode_frame(MessageType.JY61PL_SAMPLE, bytes(14), device_uuid=first_uuid)
        + encode_frame(MessageType.JY61PL_SAMPLE, bytes(14), device_uuid=second_uuid)
    )
    controller = AcquisitionController(FakeTransport([stream]), RealtimeSampleStore())

    with pytest.raises(DeviceIdentityError, match="changed UUID"):
        controller.run(Event(), idle_limit=1)


@pytest.mark.parametrize("target", ["", "usb", "UART2", "CDC ", "uart cdc"])
def test_set_livestream_rejects_invalid_targets(target: object) -> None:
    controller = AcquisitionController(FakeTransport([]), RealtimeSampleStore())

    with pytest.raises(ValueError, match="UART or CDC"):
        controller.set_livestream(target)  # type: ignore[arg-type]
