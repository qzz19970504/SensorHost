"""Run firmware real-time, SD overwrite, and explicit export acceptance modes."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

HOST_SOURCE = Path(__file__).resolve().parents[1] / "src"
if str(HOST_SOURCE) not in sys.path:
    sys.path.insert(0, str(HOST_SOURCE))

import serial
from serial.tools import list_ports

from sensor_host.protocol import Frame, MessageType, StreamParser
from sensor_host.tools.realtime_archive_models import (
    CdcExportAcceptance,
    InterruptedExportAcceptance,
    LiveAcceptance,
    OverwriteAcceptance,
    UartExportAcceptance,
)

_SENSOR_TYPES = {MessageType.IIS3DWB_FIFO, MessageType.JY61PL_SAMPLE}
_STATE_PATTERN = re.compile(r"\+STATE:([A-Z]+)")
_UUID_PATTERN = re.compile(
    r"\+UUID:([0-9a-fA-F-]{36}),SOURCE=(DERIVED|CONFIGURED)"
)
_SD_PATTERN = re.compile(
    r"\+SD:USED=(\d+),CAPACITY=(\d+),PENDING_FRAMES=(\d+),"
    r"RETAINED_CHUNKS=(\d+),RETAINED_FRAMES=(\d+),"
    r"OVERWRITTEN_CHUNKS=(\d+),OVERWRITTEN_FRAMES=(\d+)"
)
_LIVE_DROP_PATTERN = re.compile(
    r"\+LIVE_DROPS:UART_IIS=(\d+),UART_JY=(\d+),CDC=(\d+)"
)


class PortReader(threading.Thread):
    """Continuously persist and parse one serial endpoint."""

    def __init__(self, port: serial.Serial, raw_path: Path, counters_only: bool) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.raw_path = raw_path
        self.counters_only = counters_only
        self.parser = StreamParser()
        self.frames: list[Frame] = []
        self.cli: list[str] = []
        self.statuses: list[Any] = []
        self.sensor_frames = 0
        self.last_sensor_sequence: int | None = None
        self.bytes_received = 0
        self.error: str | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def run(self) -> None:
        try:
            with self.raw_path.open("wb") as raw_file:
                while not self._stop_event.is_set():
                    chunk = self.port.read(max(self.port.in_waiting, 1))
                    if not chunk:
                        continue
                    raw_file.write(chunk)
                    raw_file.flush()
                    decoded = self.parser.feed(chunk)
                    with self._lock:
                        self.bytes_received += len(chunk)
                        for frame in decoded:
                            if frame.message_type in _SENSOR_TYPES:
                                self.sensor_frames += 1
                                self.last_sensor_sequence = frame.sequence
                            if frame.cli_text is not None:
                                self.cli.append(frame.cli_text)
                            if frame.status is not None:
                                self.statuses.append(frame.status)
                            if not self.counters_only:
                                self.frames.append(frame)
        except (OSError, serial.SerialException) as error:
            self.error = str(error)

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=2.0)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "frames": len(self.frames),
                "cli": len(self.cli),
                "statuses": len(self.statuses),
                "sensor_frames": self.sensor_frames,
                "last_sensor_sequence": self.last_sensor_sequence,
                "bytes": self.bytes_received,
                "parser": dataclasses.asdict(self.parser.stats),
            }

    def frames_since(self, marker: dict[str, Any]) -> list[Frame]:
        with self._lock:
            return list(self.frames[marker["frames"] :])

    def cli_since(self, count: int) -> str:
        with self._lock:
            return "".join(self.cli[count:])

    def latest_status(self) -> Any | None:
        with self._lock:
            return self.statuses[-1] if self.statuses else None


def _wait_until(predicate: Callable[[], bool], timeout_s: float,
                description: str) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise TimeoutError(f"timed out waiting for {description}")


def _parse_state(text: str) -> dict[str, Any]:
    state_match = _STATE_PATTERN.search(text)
    uuid_match = _UUID_PATTERN.search(text)
    sd_match = _SD_PATTERN.search(text)
    drops_match = _LIVE_DROP_PATTERN.search(text)
    if not all((state_match, uuid_match, sd_match, drops_match)):
        raise ValueError(f"incomplete AT+STATE response: {text!r}")
    sd = tuple(int(value) for value in sd_match.groups())
    drops = tuple(int(value) for value in drops_match.groups())
    return {
        "state": state_match.group(1),
        "uuid": uuid_match.group(1).lower(),
        "uuid_source": uuid_match.group(2),
        "sd_used": sd[0],
        "sd_capacity": sd[1],
        "pending_frames": sd[2],
        "retained_chunks": sd[3],
        "retained_frames": sd[4],
        "overwritten_chunks": sd[5],
        "overwritten_frames": sd[6],
        "uart_iis_live_drops": drops[0],
        "uart_jy_live_drops": drops[1],
        "cdc_live_drops": drops[2],
    }


def _sensor_frames(frames: list[Frame], archive: bool | None = None) -> list[Frame]:
    selected = [frame for frame in frames if frame.message_type in _SENSOR_TYPES]
    if archive is not None:
        selected = [frame for frame in selected if frame.archive_export is archive]
    return selected


def _missing_after_dedup(frames: list[Frame]) -> int:
    identities = sorted({(str(frame.device_uuid), frame.sequence) for frame in frames})
    if len(identities) < 2:
        return 0
    missing = 0
    by_uuid: dict[str, list[int]] = {}
    for device_uuid, sequence in identities:
        by_uuid.setdefault(device_uuid, []).append(sequence)
    for sequences in by_uuid.values():
        for previous, current in zip(sequences, sequences[1:]):
            if current > previous + 1:
                missing += current - previous - 1
    return missing


class AcceptanceSession:
    def __init__(self, arguments: argparse.Namespace) -> None:
        self.arguments = arguments
        output = arguments.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        self.uart_raw_path = output.with_suffix(".uart.sdf1")
        self.cdc_raw_path = output.with_suffix(".cdc.sdf1")
        self.uart_port: serial.Serial | None = None
        self.cdc_port: serial.Serial | None = None
        self.uart: PortReader | None = None
        self.cdc: PortReader | None = None

    def __enter__(self) -> "AcceptanceSession":
        counters_only = self.arguments.mode == "overwrite"
        self.cdc_port = serial.Serial(self.arguments.cdc_port, 115200,
                                      timeout=0.02)
        self.uart_port = serial.Serial(self.arguments.uart_port,
                                       self.arguments.uart_baud, timeout=0.02)
        self.cdc_port.reset_input_buffer()
        self.uart_port.reset_input_buffer()
        self.cdc = PortReader(self.cdc_port, self.cdc_raw_path, counters_only)
        self.uart = PortReader(self.uart_port, self.uart_raw_path, counters_only)
        self.cdc.start()
        self.uart.start()
        return self

    def __exit__(self, *_: object) -> None:
        assert self.uart is not None and self.cdc is not None
        self.uart.stop()
        self.cdc.stop()
        assert self.uart_port is not None and self.cdc_port is not None
        self.uart_port.close()
        self.cdc_port.close()

    def command(self, command: str, expected: str = "OK",
                timeout_s: float = 3.0) -> str:
        assert self.cdc is not None and self.cdc_port is not None
        marker = self.cdc.snapshot()["cli"]
        encoded = command.encode("ascii") + b"\r\n"
        if self.cdc_port.write(encoded) != len(encoded):
            raise OSError(f"short control write for {command}")
        self.cdc_port.flush()
        _wait_until(lambda: expected in self.cdc.cli_since(marker), timeout_s,
                    f"{command} response containing {expected!r}")
        return self.cdc.cli_since(marker)

    def state(self) -> dict[str, Any]:
        return _parse_state(self.command("AT+STATE?", "+STATE:"))

    def status(self) -> Any:
        assert self.cdc is not None
        marker = self.cdc.snapshot()["statuses"]
        self.command("status")
        _wait_until(lambda: self.cdc.snapshot()["statuses"] > marker, 3.0,
                    "binary STATUS frame")
        return self.cdc.latest_status()

    def stop_and_wait(self) -> tuple[float, dict[str, Any]]:
        started = time.monotonic()
        self.command("AT+STOP", timeout_s=3.0)
        elapsed = time.monotonic() - started
        state = self.state()
        if state["state"] != "IDLE":
            raise RuntimeError(f"STOP completed in unexpected state {state['state']}")
        self.wait_for_inflight_completion()
        return elapsed, state

    def wait_for_inflight_completion(self) -> None:
        assert self.uart is not None and self.cdc is not None
        stable_since = time.monotonic()
        previous = (self.uart.snapshot()["bytes"], self.cdc.snapshot()["bytes"])
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            time.sleep(0.02)
            current = (self.uart.snapshot()["bytes"], self.cdc.snapshot()["bytes"])
            if current != previous:
                previous = current
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= 0.1:
                return
        raise TimeoutError("live transports did not become idle after STOP")


def _parser_delta(end: dict[str, Any], start: dict[str, Any], name: str) -> int:
    return int(end["parser"][name]) - int(start["parser"][name])


def _run_preflight(session: AcceptanceSession) -> dict[str, Any]:
    state = session.state()
    cdc_stream = session.command("AT+CDCSTREAM?", "+CDCSTREAM:")
    uuid_reply = session.command("AT+UUID?", "+UUID:")
    status = session.status()
    passed = (
        state["state"] == "IDLE"
        and "+CDCSTREAM:OFF" in cdc_stream
        and state["uuid"] in uuid_reply.lower()
        and status is not None
    )
    return {"passed": passed, "state": state, "cdc_stream": cdc_stream,
            "uuid_reply": uuid_reply}


def _run_live(session: AcceptanceSession) -> dict[str, Any]:
    assert session.uart is not None and session.cdc is not None
    session.command("AT+SDCLEAR=CONFIRM", timeout_s=5.0)
    session.command("AT+CDCSTREAM=OFF")
    state_before = session.state()
    status_before = session.status()
    uart_start, cdc_start = session.uart.snapshot(), session.cdc.snapshot()
    session.command("AT+START")
    time.sleep(min(0.3, session.arguments.duration / 4.0))
    cdc_off_frames = session.cdc.snapshot()["sensor_frames"] - cdc_start["sensor_frames"]
    session.command("AT+CDCSTREAM=ON")
    max_lag = 0
    deadline = time.monotonic() + session.arguments.duration
    while time.monotonic() < deadline:
        uart_sequence = session.uart.snapshot()["last_sensor_sequence"]
        cdc_sequence = session.cdc.snapshot()["last_sensor_sequence"]
        if uart_sequence is not None and cdc_sequence is not None:
            max_lag = max(max_lag, max(0, cdc_sequence - uart_sequence))
        time.sleep(0.05)
    state_during = session.state()
    status_after = session.status()
    session.stop_and_wait()
    uart_end, cdc_end = session.uart.snapshot(), session.cdc.snapshot()
    uart_frames = _sensor_frames(session.uart.frames_since(uart_start))
    cdc_frames = _sensor_frames(session.cdc.frames_since(cdc_start))
    model = LiveAcceptance(
        uart_frames=len(uart_frames), cdc_frames=len(cdc_frames),
        uart_max_sequence_lag=max_lag,
        uart_crc_errors=_parser_delta(uart_end, uart_start, "crc_errors"),
        cdc_crc_errors=_parser_delta(cdc_end, cdc_start, "crc_errors"),
        cdc_live_drop_delta=(state_during["cdc_live_drops"] -
                             state_before["cdc_live_drops"]),
        source_drop_delta=status_after.source_drops - status_before.source_drops,
    )
    types = {frame.message_type for frame in uart_frames + cdc_frames}
    uuids = {str(frame.device_uuid) for frame in uart_frames + cdc_frames}
    passed = (model.passed and cdc_off_frames == 0 and
              types == _SENSOR_TYPES and uuids == {state_before["uuid"]})
    return {"passed": passed, "acceptance": dataclasses.asdict(model),
            "cdc_off_sensor_frames": cdc_off_frames,
            "sensor_types": sorted(item.name for item in types),
            "observed_uuids": sorted(uuids)}


def _run_overwrite(session: AcceptanceSession) -> dict[str, Any]:
    session.command("AT+SDCLEAR=CONFIRM", timeout_s=5.0)
    session.command("AT+CDCSTREAM=OFF")
    before = session.state()
    status_before = session.status()
    session.command("AT+START")
    remained_acquiring = True
    deadline = time.monotonic() + session.arguments.duration
    latest = before
    while time.monotonic() < deadline:
        time.sleep(min(5.0, max(0.02, deadline - time.monotonic())))
        latest = session.state()
        remained_acquiring &= latest["state"] == "ACQUIRE"
    status_after = session.status()
    stop_latency, stopped = session.stop_and_wait()
    model = OverwriteAcceptance(
        duration_s=session.arguments.duration,
        remained_acquiring=remained_acquiring,
        overwritten_chunks_delta=(latest["overwritten_chunks"] -
                                   before["overwritten_chunks"]),
        overwritten_frames_delta=(latest["overwritten_frames"] -
                                   before["overwritten_frames"]),
        source_drop_delta=status_after.source_drops - status_before.source_drops,
        sd_errors=status_after.spi_dma_errors - status_before.spi_dma_errors,
        transport_errors=(status_after.uart_dma_errors - status_before.uart_dma_errors +
                          status_after.cdc_errors - status_before.cdc_errors),
        stop_latency_s=stop_latency, stopped_idle=stopped["state"] == "IDLE",
        retained_frames=stopped["retained_frames"],
    )
    return {"passed": model.passed, "acceptance": dataclasses.asdict(model)}


def _export_model(session: AcceptanceSession, target: str,
                  expected_uuid: str, uart_marker: dict[str, Any],
                  cdc_marker: dict[str, Any], elapsed: float,
                  terminal_text: str) -> UartExportAcceptance:
    assert session.uart is not None and session.cdc is not None
    uart_frames = _sensor_frames(session.uart.frames_since(uart_marker), archive=True)
    cdc_frames = _sensor_frames(session.cdc.frames_since(cdc_marker), archive=True)
    selected, wrong = ((uart_frames, cdc_frames) if target == "UART"
                       else (cdc_frames, uart_frames))
    selected_end = (session.uart.snapshot() if target == "UART"
                    else session.cdc.snapshot())
    selected_start = uart_marker if target == "UART" else cdc_marker
    observed = tuple(sorted({str(frame.device_uuid) for frame in selected}))
    identities = [(str(frame.device_uuid), frame.sequence) for frame in selected]
    common = dict(
        frames=len(selected),
        iis_frames=sum(frame.message_type is MessageType.IIS3DWB_FIFO
                       for frame in selected),
        jy_frames=sum(frame.message_type is MessageType.JY61PL_SAMPLE
                      for frame in selected),
        expected_uuid=expected_uuid, observed_uuids=observed,
        archive_flag_errors=sum(not frame.archive_export for frame in selected),
        crc_errors=_parser_delta(selected_end, selected_start, "crc_errors"),
        length_errors=_parser_delta(selected_end, selected_start, "length_errors"),
        payload_errors=_parser_delta(selected_end, selected_start, "payload_errors"),
        duplicate_frames=len(identities) - len(set(identities)),
        missing_after_dedup=_missing_after_dedup(selected),
        terminal_seen="EXPORT_END:" in terminal_text,
        storage_empty=session.state()["retained_frames"] == 0,
        wrong_route_frames=len(wrong),
    )
    if target == "CDC":
        raw_bytes = sum(len(frame.payload) + 48 for frame in selected)
        uart_wire_seconds = raw_bytes * 10.0 / session.arguments.uart_baud
        return CdcExportAcceptance(
            **common,
            control_responses_valid="OK" in terminal_text,
            faster_than_uart=elapsed < uart_wire_seconds,
        )
    return UartExportAcceptance(**common)


def _prepare_short_archive(session: AcceptanceSession) -> dict[str, Any]:
    session.command("AT+SDCLEAR=CONFIRM", timeout_s=5.0)
    session.command("AT+CDCSTREAM=OFF")
    identity = session.state()
    session.command("AT+START")
    time.sleep(session.arguments.duration)
    session.stop_and_wait()
    return identity


def _run_export(session: AcceptanceSession, target: str) -> dict[str, Any]:
    assert session.uart is not None and session.cdc is not None
    identity = _prepare_short_archive(session)
    uart_marker, cdc_marker = session.uart.snapshot(), session.cdc.snapshot()
    cli_marker = cdc_marker["cli"]
    started = time.monotonic()
    session.command(f"AT+EXPORT={target}", "EXPORT_BEGIN:")
    _wait_until(lambda: "EXPORT_END:" in session.cdc.cli_since(cli_marker),
                max(30.0, session.arguments.duration * 20.0), "EXPORT_END")
    elapsed = time.monotonic() - started
    terminal = session.cdc.cli_since(cli_marker)
    model = _export_model(session, target, identity["uuid"], uart_marker,
                          cdc_marker, elapsed, terminal)
    return {"passed": model.passed, "acceptance": dataclasses.asdict(model),
            "elapsed_s": elapsed}


def _run_interrupt_export(session: AcceptanceSession) -> dict[str, Any]:
    assert session.uart is not None and session.cdc is not None
    identity = _prepare_short_archive(session)
    first_marker = session.cdc.snapshot()
    session.command("AT+EXPORT=CDC", "EXPORT_BEGIN:")
    _wait_until(lambda: len(_sensor_frames(session.cdc.frames_since(first_marker),
                                           archive=True)) >= 1,
                5.0, "first exported frame")
    session.command("AT+START")
    resumed = session.state()["state"] == "ACQUIRE"
    first_frames = _sensor_frames(session.cdc.frames_since(first_marker), archive=True)
    time.sleep(min(1.0, session.arguments.duration))
    session.stop_and_wait()
    second_marker = session.cdc.snapshot()
    cli_marker = second_marker["cli"]
    session.command("AT+EXPORT=CDC", "EXPORT_BEGIN:")
    _wait_until(lambda: "EXPORT_END:" in session.cdc.cli_since(cli_marker),
                max(30.0, session.arguments.duration * 20.0), "resumed EXPORT_END")
    second_frames = _sensor_frames(session.cdc.frames_since(second_marker), archive=True)
    all_frames = first_frames + second_frames
    first_ids = {(str(frame.device_uuid), frame.sequence) for frame in first_frames}
    second_ids = {(str(frame.device_uuid), frame.sequence) for frame in second_frames}
    end = session.cdc.snapshot()
    model = InterruptedExportAcceptance(
        first_export_frames=len(first_frames), resumed_export_frames=len(second_frames),
        duplicate_frames=len(first_ids & second_ids),
        missing_after_dedup=_missing_after_dedup(all_frames),
        uuid_mismatches=sum(str(frame.device_uuid) != identity["uuid"]
                            for frame in all_frames),
        archive_flag_errors=sum(not frame.archive_export for frame in all_frames),
        crc_errors=_parser_delta(end, first_marker, "crc_errors"),
        length_errors=_parser_delta(end, first_marker, "length_errors"),
        payload_errors=_parser_delta(end, first_marker, "payload_errors"),
        resumed_acquire=resumed,
        final_storage_empty=session.state()["retained_frames"] == 0,
    )
    return {"passed": model.passed, "acceptance": dataclasses.asdict(model)}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-ports", action="store_true")
    parser.add_argument("--mode", choices=("preflight", "live", "overwrite",
                                            "export-uart", "export-cdc",
                                            "interrupt-export"))
    parser.add_argument("--cdc-port")
    parser.add_argument("--uart-port")
    parser.add_argument("--uart-baud", type=int, default=115200)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if not arguments.list_ports:
        missing = [name for name in ("mode", "cdc_port", "uart_port", "output")
                   if getattr(arguments, name) is None]
        if missing:
            parser.error("acceptance requires --mode, --cdc-port, --uart-port and --output")
        if arguments.duration <= 0.0:
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


def main() -> int:
    arguments = _arguments()
    if arguments.list_ports:
        return _show_ports()
    runners = {
        "preflight": _run_preflight,
        "live": _run_live,
        "overwrite": _run_overwrite,
        "export-uart": lambda session: _run_export(session, "UART"),
        "export-cdc": lambda session: _run_export(session, "CDC"),
        "interrupt-export": _run_interrupt_export,
    }
    output = arguments.output.resolve()
    try:
        with AcceptanceSession(arguments) as session:
            result = runners[arguments.mode](session)
            assert session.uart is not None and session.cdc is not None
            result.update({
                "generated_utc": datetime.now(timezone.utc).isoformat(),
                "mode": arguments.mode,
                "cdc_port": arguments.cdc_port,
                "uart_port": arguments.uart_port,
                "uart_baud": arguments.uart_baud,
                "duration_s": arguments.duration,
                "uart_raw": str(session.uart_raw_path),
                "cdc_raw": str(session.cdc_raw_path),
                "uart_reader_error": session.uart.error,
                "cdc_reader_error": session.cdc.error,
                "uart_parser": session.uart.snapshot()["parser"],
                "cdc_parser": session.cdc.snapshot()["parser"],
            })
            result["passed"] = bool(result["passed"] and not session.uart.error
                                    and not session.cdc.error)
    except (OSError, ValueError, RuntimeError, TimeoutError,
            serial.SerialException) as error:
        result = {"passed": False, "mode": arguments.mode,
                  "error": str(error),
                  "generated_utc": datetime.now(timezone.utc).isoformat()}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
