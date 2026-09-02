"""Capture and compare UART-authoritative and CDC-mirrored SDF1 streams."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

HOST_SOURCE = Path(__file__).resolve().parents[1] / "src"
if str(HOST_SOURCE) not in sys.path:
    sys.path.insert(0, str(HOST_SOURCE))

import serial
from serial.tools import list_ports

from sensor_host.protocol import MessageType, StreamParser
from sensor_host.tools.dual_output_compare import compare_sensor_frames


class PortReader(threading.Thread):
    def __init__(self, port: serial.Serial) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.data = bytearray()
        self.error: str | None = None
        self._stop_event = threading.Event()

    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                chunk = self.port.read(max(self.port.in_waiting, 1))
                if chunk:
                    self.data.extend(chunk)
        except (OSError, serial.SerialException) as error:
            self.error = str(error)

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=2.0)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-ports", action="store_true")
    parser.add_argument("--cdc-port")
    parser.add_argument("--uart-port")
    parser.add_argument("--uart-baud", type=int)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if not arguments.list_ports:
        missing = [name for name in ("cdc_port", "uart_port", "uart_baud",
                                      "duration", "output")
                   if getattr(arguments, name) is None]
        if missing:
            parser.error("capture requires --cdc-port, --uart-port, --uart-baud, "
                         "--duration and --output")
        if arguments.duration <= 0:
            parser.error("--duration must be positive")
        if not 9600 <= arguments.uart_baud <= 3_000_000:
            parser.error("--uart-baud must be in 9600..3000000")
    return arguments


def _show_ports() -> int:
    for port in list_ports.comports():
        vid = f"{port.vid:04X}" if port.vid is not None else "----"
        pid = f"{port.pid:04X}" if port.pid is not None else "----"
        print(f"{port.device}\t{port.description}\tVID:PID={vid}:{pid}")
    return 0


def _parse(raw: bytes) -> tuple[StreamParser, list[object]]:
    parser = StreamParser()
    frames = parser.feed(raw)
    return parser, frames


def _capture(arguments: argparse.Namespace) -> int:
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    uart_raw_path = output.with_suffix(".uart.sdf1")
    cdc_raw_path = output.with_suffix(".cdc.sdf1")

    with serial.Serial(arguments.cdc_port, 115200, timeout=0.02) as cdc, \
         serial.Serial(arguments.uart_port, arguments.uart_baud,
                       timeout=0.02) as uart:
        cdc.reset_input_buffer()
        uart.reset_input_buffer()
        cdc_reader = PortReader(cdc)
        uart_reader = PortReader(uart)
        cdc_reader.start()
        uart_reader.start()
        try:
            cdc.write(b"AT\r\nAT+STATE?\r\nAT+START\r\n")
            cdc.flush()
            time.sleep(arguments.duration)
            cdc.write(b"AT+STOP\r\n")
            cdc.flush()
            time.sleep(0.5)
        finally:
            cdc_reader.stop()
            uart_reader.stop()

    uart_raw = bytes(uart_reader.data)
    cdc_raw = bytes(cdc_reader.data)
    uart_raw_path.write_bytes(uart_raw)
    cdc_raw_path.write_bytes(cdc_raw)
    uart_parser, uart_frames = _parse(uart_raw)
    cdc_parser, cdc_frames = _parse(cdc_raw)
    comparison = compare_sensor_frames(uart_frames, cdc_frames)
    uart_types = {frame.message_type for frame in uart_frames}
    serial_errors = tuple(error for error in (uart_reader.error, cdc_reader.error)
                          if error)
    passed = (
        not serial_errors
        and uart_parser.stats.crc_errors == 0
        and cdc_parser.stats.crc_errors == 0
        and uart_parser.stats.sequence_gaps == 0
        and not comparison.uart_only_sequences
        and not comparison.cdc_only_sequences
        and not comparison.content_mismatches
        and MessageType.IIS3DWB_FIFO in uart_types
        and MessageType.JY61PL_SAMPLE in uart_types
    )
    document = {
        "passed": passed,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "cdc_port": arguments.cdc_port,
        "uart_port": arguments.uart_port,
        "uart_baud": arguments.uart_baud,
        "duration_s": arguments.duration,
        "commands_sent_via_cdc": ["AT", "AT+STATE?", "AT+START", "AT+STOP"],
        "ack_sent": False,
        "uart_raw": str(uart_raw_path),
        "cdc_raw": str(cdc_raw_path),
        "serial_errors": serial_errors,
        "uart_parser": dataclasses.asdict(uart_parser.stats),
        "cdc_parser": dataclasses.asdict(cdc_parser.stats),
        "comparison": dataclasses.asdict(comparison),
        "uart_has_iis3dwb": MessageType.IIS3DWB_FIFO in uart_types,
        "uart_has_jy61p": MessageType.JY61PL_SAMPLE in uart_types,
    }
    output.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(json.dumps(document, indent=2))
    return 0 if passed else 1


def main() -> int:
    arguments = _arguments()
    if arguments.list_ports:
        return _show_ports()
    try:
        return _capture(arguments)
    except (OSError, serial.SerialException) as error:
        print(f"dual-output acceptance failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
