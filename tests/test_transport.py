from types import SimpleNamespace

import pytest

from sensor_host.transport import CdcSerialTransport


class FakeSerial:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.is_closed = False
        self.in_waiting = 3
        self.timeout = 0.0

    def read(self, count: int) -> bytes:
        return b"abc"[:count]

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def close(self) -> None:
        self.is_closed = True


def test_cdc_adapter_reads_and_normalizes_control_line() -> None:
    fake_serial = FakeSerial()
    transport = CdcSerialTransport(
        serial_factory=lambda **_arguments: fake_serial,
    )
    transport.open("COM7")

    assert transport.read(max_bytes=64, timeout_s=0.05) == b"abc"
    transport.write_control(b"status\n")
    transport.close()

    assert fake_serial.timeout == 0.05
    assert fake_serial.writes == [b"status\r\n"]
    assert fake_serial.is_closed is True


def test_cdc_discovery_preserves_port_identity() -> None:
    port = SimpleNamespace(
        device="COM7",
        description="STM32 Virtual COM Port",
        vid=0x0483,
        pid=0x5740,
    )
    transport = CdcSerialTransport(port_enumerator=lambda: [port])

    devices = transport.discover()

    assert devices[0].device_id == "COM7"
    assert devices[0].label == "COM7 — STM32 Virtual COM Port"
    assert devices[0].vid == 0x0483
    assert devices[0].pid == 0x5740


@pytest.mark.parametrize("command", [b"", b"bad\x00command", b"x" * 95])
def test_cdc_adapter_rejects_invalid_control_lines(command: bytes) -> None:
    fake_serial = FakeSerial()
    transport = CdcSerialTransport(
        serial_factory=lambda **_arguments: fake_serial,
    )
    transport.open("COM7")

    with pytest.raises(ValueError):
        transport.write_control(command)

    assert fake_serial.writes == []
