from threading import Event

import pytest

from sensor_host.acquisition import AcquisitionController, RealtimeSampleStore


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
