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
    sequence_lag,
)

_SENSOR_TYPES = {MessageType.IIS3DWB_FIFO, MessageType.JY61PL_SAMPLE}
_STATE_PATTERN = re.compile(r"\+STATE:([A-Z]+)")
_UUID_PATTERN = re.compile(
    r"\+UUID:([0-9a-fA-F-]{36}),SOURCE=(DERIVED|CONFIGURED)"
)
_SD_PATTERN = re.compile(
    r"\+SD:USED=(\d+),CAPACITY=(\d+),PENDING_FRAMES=(\d+),"
    r"RETAINED_CHUNKS=(\d+),RETAINED_FRAMES=(\d+),"
    r"OVERWRITTEN_CHUNKS=(\d+),OVERWRITTEN_FRAMES=(\d+),"
    r"READY=([01]),FORMAT_REQUIRED=([01])"
)
_LIVE_PATTERN = re.compile(
    r"\+LIVE:TARGET=(UART|CDC),DROPS_IIS=(\d+),DROPS_JY=(\d+),"
    r"LAST_ROUTED_SEQUENCE=(\d+),LAST_COMPLETED_SEQUENCE=(\d+)"
)
_LIVESTREAM_PATTERN = re.compile(r"\+LIVESTREAM:(UART|CDC)")
_BAUD_PATTERN = re.compile(r"\+BAUD:(\d+)")


class PortReader(threading.Thread):
    """Continuously persist and parse one serial endpoint."""

    def __init__(self, port: serial.Serial, raw_path: Path, counters_only: bool,
                 decode_sensor_payload: bool = True) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.raw_path = raw_path
        self.counters_only = counters_only
        self.parser = StreamParser(decode_sensor_payload=decode_sensor_payload)
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
    """Parse AT+STATE? response text into a structured dict.

    C5: FORMAT_REQUIRED=1 is a valid structured result, not an error.
    C6: ERROR:RESPONSE_TOO_LARGE is recognised as a diagnostic condition.
    D2: ERROR:TX_BUSY (control buffer pool exhausted, counts command_error) is
    recognised as a transient diagnostic rather than an incomplete response.
    """
    if "ERROR:RESPONSE_TOO_LARGE" in text:
        raise ValueError(
            "firmware returned ERROR:RESPONSE_TOO_LARGE — +STATE response "
            "exceeds internal buffer; reduce concurrent state complexity"
        )
    if "ERROR:TX_BUSY" in text:
        raise ValueError(
            "firmware returned ERROR:TX_BUSY — control buffer pool exhausted "
            "(transient, counts command_error); back off and retry the query"
        )
    state_match = _STATE_PATTERN.search(text)
    uuid_match = _UUID_PATTERN.search(text)
    sd_match = _SD_PATTERN.search(text)
    live_match = _LIVE_PATTERN.search(text)
    if not all((state_match, uuid_match, sd_match, live_match)):
        raise ValueError(f"incomplete AT+STATE response: {text!r}")
    sd = tuple(int(value) for value in sd_match.groups())
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
        "sd_ready": bool(sd[7]),
        "sd_format_required": bool(sd[8]),
        "live_target": live_match.group(1),
        "drops_iis": int(live_match.group(2)),
        "drops_jy": int(live_match.group(3)),
        "last_routed_sequence": int(live_match.group(4)),
        "last_completed_sequence": int(live_match.group(5)),
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
        lightweight = self.arguments.mode in ("live-uart", "live-cdc")
        self.cdc = PortReader(self.cdc_port, self.cdc_raw_path, counters_only,
                              decode_sensor_payload=not lightweight)
        self.uart = PortReader(self.uart_port, self.uart_raw_path, counters_only,
                               decode_sensor_payload=not lightweight)
        self.cdc.start()
        self.uart.start()
        # Windows may finish CDC line-state negotiation just after pyserial
        # opens the port.  A command written in that window can be accepted by
        # the host API but never reach the device OUT endpoint.
        time.sleep(0.25)
        return self

    def __exit__(self, *_: object) -> None:
        assert self.uart is not None and self.cdc is not None
        self.uart.stop()
        self.cdc.stop()
        assert self.uart_port is not None and self.cdc_port is not None
        self.uart_port.close()
        self.cdc_port.close()

    def command(self, command: str, expected: str = "OK",
                timeout_s: float = 3.0, via: str = "cdc",
                busy_retries: int = 3) -> str:
        """Send a command via the specified control link ('cdc' or 'uart').

        C8: During live modes, control/polling goes through the non-target link
        to avoid polluting the data link's frame statistics.
        C6: Recognises ERROR:RESPONSE_TOO_LARGE as a structured diagnostic.
        D2/R5: ERROR:BUSY (e.g. AT+LIVESTREAM= while a live transfer is still
        in flight in IDLE) and ERROR:TX_BUSY (control buffer pool exhausted,
        counts command_error) are transient.  Back off and retry a bounded
        number of times instead of treating them as a fatal RuntimeError.
        """
        assert self.cdc is not None and self.cdc_port is not None
        assert self.uart is not None and self.uart_port is not None
        if via == "uart":
            port = self.uart_port
            reader = self.uart
        else:
            port = self.cdc_port
            reader = self.cdc
        encoded = command.encode("ascii") + b"\r\n"
        attempt = 0
        while True:
            marker = reader.snapshot()["cli"]
            if port.write(encoded) != len(encoded):
                raise OSError(f"short control write for {command} via {via}")
            port.flush()
            deadline = time.monotonic() + timeout_s
            busy = False
            while time.monotonic() < deadline:
                response = reader.cli_since(marker)
                if expected in response:
                    return response
                if "ERROR:RESPONSE_TOO_LARGE" in response:
                    raise ValueError(
                        f"{command} via {via}: firmware buffer overflow "
                        "(ERROR:RESPONSE_TOO_LARGE)")
                if "ERROR:BUSY" in response or "ERROR:TX_BUSY" in response:
                    busy = True
                    break
                if "ERROR:" in response:
                    raise RuntimeError(
                        f"{command} via {via} returned {response.strip()}")
                time.sleep(0.02)
            if not busy:
                raise TimeoutError(
                    f"timed out waiting for {command} via {via} response "
                    f"containing {expected!r}")
            if attempt >= busy_retries:
                raise RuntimeError(
                    f"{command} via {via} stayed transiently busy "
                    f"(ERROR:BUSY/ERROR:TX_BUSY) after {busy_retries} "
                    f"backoff retries")
            time.sleep(0.5 * (2 ** attempt))
            attempt += 1

    def state(self, via: str = "cdc") -> dict[str, Any]:
        return _parse_state(self.command("AT+STATE?", "+STATE:", via=via))

    def status(self, via: str = "cdc") -> Any:
        if via == "uart":
            reader = self.uart
        else:
            reader = self.cdc
        assert reader is not None
        marker = reader.snapshot()["statuses"]
        self.command("status", via=via)
        _wait_until(lambda: reader.snapshot()["statuses"] > marker, 3.0,
                    "binary STATUS frame")
        return reader.latest_status()

    def stop_and_wait(self, via: str = "cdc") -> tuple[float, dict[str, Any]]:
        """C1: Measure STOP→OK latency and verify zero post-STOP sensor frames."""
        assert self.uart is not None and self.cdc is not None
        started = time.monotonic()
        self.command("AT+STOP", timeout_s=3.0, via=via)
        elapsed = time.monotonic() - started
        state = self.state(via=via)
        if state["state"] != "IDLE":
            raise RuntimeError(f"STOP completed in unexpected state {state['state']}")
        self.wait_for_inflight_completion()
        return elapsed, state

    def post_stop_sensor_frame_count(self, wait_s: float = 1.0) -> int:
        """C1: After STOP OK, snapshot both links, wait, then count new sensor frames."""
        assert self.uart is not None and self.cdc is not None
        uart_before = self.uart.snapshot()["sensor_frames"]
        cdc_before = self.cdc.snapshot()["sensor_frames"]
        time.sleep(wait_s)
        uart_after = self.uart.snapshot()["sensor_frames"]
        cdc_after = self.cdc.snapshot()["sensor_frames"]
        return (uart_after - uart_before) + (cdc_after - cdc_before)

    def probe_nontarget_at(self, via: str) -> bool:
        """C8: Verify the non-target link responds to AT and AT+STATE?."""
        try:
            reply = self.command("AT", "OK", timeout_s=2.0, via=via)
            if "OK" not in reply:
                return False
            reply = self.command("AT+STATE?", "+STATE:", timeout_s=2.0, via=via)
            return "+STATE:" in reply
        except (RuntimeError, TimeoutError, OSError, ValueError):
            return False

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
    """C5: FORMAT_REQUIRED produces a structured result, not an exception."""
    state = session.state()
    # C5: If FORMAT_REQUIRED, return structured failure immediately
    if state["sd_format_required"]:
        return {
            "passed": False,
            "reason": "SD card requires formatting (FORMAT_REQUIRED=1)",
            "state": state,
        }
    deadline = time.monotonic() + max(30.0, session.arguments.duration)
    while not state["sd_ready"] and time.monotonic() < deadline:
        time.sleep(1.0)
        state = session.state()
        if state["sd_format_required"]:
            return {
                "passed": False,
                "reason": "SD card requires formatting (FORMAT_REQUIRED=1)",
                "state": state,
            }
    livestream_reply = session.command("AT+LIVESTREAM?", "+LIVESTREAM:")
    livestream_match = _LIVESTREAM_PATTERN.search(livestream_reply)
    livestream_target = livestream_match.group(1) if livestream_match else ""
    uuid_reply = session.command("AT+UUID?", "+UUID:")
    status = session.status()
    passed = (
        state["state"] == "IDLE"
        and state["sd_ready"]
        and not state["sd_format_required"]
        and livestream_target == "UART"  # cold-boot default
        and state["live_target"] == "UART"
        and state["uuid"] in uuid_reply.lower()
        and status is not None
    )
    return {"passed": passed, "state": state, "livestream": livestream_reply,
            "uuid_reply": uuid_reply}


def _run_live(session: AcceptanceSession, target: str) -> dict[str, Any]:
    """Run live streaming acceptance for a single target (UART or CDC).

    C8: Control/polling goes through the non-target link.
    C2: Sequence lag baseline reset after SDCLEAR.
    C1: Post-STOP zero sensor frame assertion.
    """
    assert session.uart is not None and session.cdc is not None
    # C8: control link is the opposite of the data target
    control_via = "cdc" if target == "UART" else "uart"

    session.command("AT+SDCLEAR=CONFIRM", timeout_s=5.0, via=control_via)
    session.command(f"AT+LIVESTREAM={target}", via=control_via)
    state_before = session.state(via=control_via)
    assert state_before["live_target"] == target
    status_before = session.status(via=control_via)

    # C8: Probe non-target link AT responsiveness before starting
    nontarget_at_pre = session.probe_nontarget_at(via=control_via)

    uart_start, cdc_start = session.uart.snapshot(), session.cdc.snapshot()
    session.command("AT+START", via=control_via)

    # C2: After SDCLEAR, sequence baseline is reset; poll lag from state.
    # MN-3: probe the non-target link a second time at ~50% of the duration and
    # merge both probes into the nontarget_at_probe gate; a 50 ms poll that
    # transiently fails (e.g. ERROR:BUSY / timeout) is captured and degrades the
    # probe to False instead of aborting the whole round with TimeoutError.
    max_lag = 0
    poll_failures = 0
    midstream_probed = False
    nontarget_at_midstream = True
    duration = session.arguments.duration
    started = time.monotonic()
    deadline = started + duration
    midstream_mark = started + duration * 0.5
    while time.monotonic() < deadline:
        if not midstream_probed and time.monotonic() >= midstream_mark:
            midstream_probed = True
            nontarget_at_midstream = session.probe_nontarget_at(via=control_via)
        try:
            current_state = session.state(via=control_via)
        except (TimeoutError, RuntimeError, OSError, ValueError):
            poll_failures += 1
            time.sleep(0.05)
            continue
        lag = sequence_lag(current_state["last_routed_sequence"],
                           current_state["last_completed_sequence"])
        max_lag = max(max_lag, lag)
        time.sleep(0.05)

    # MN-3: merge pre-START and mid-stream probes; unreliable polling means the
    # non-target control link was not provably responsive throughout the run.
    nontarget_at_ok = (nontarget_at_pre and nontarget_at_midstream
                       and poll_failures == 0)

    state_during = session.state(via=control_via)
    status_after = session.status(via=control_via)
    stop_latency, stopped = session.stop_and_wait(via=control_via)

    # C1: Verify zero sensor frames arrive after STOP OK
    post_stop_frames = session.post_stop_sensor_frame_count(wait_s=1.0)

    uart_end, cdc_end = session.uart.snapshot(), session.cdc.snapshot()
    uart_frames = _sensor_frames(session.uart.frames_since(uart_start))
    cdc_frames = _sensor_frames(session.cdc.frames_since(cdc_start))

    # Determine target vs non-target frames and error deltas
    if target == "UART":
        target_frames_list = uart_frames
        nontarget_frames_list = cdc_frames
        target_end, target_start_snap = uart_end, uart_start
        nontarget_end, nontarget_start_snap = cdc_end, cdc_start
        physical_tx_delta = (status_after.uart_dma_errors -
                             status_before.uart_dma_errors)
    else:
        target_frames_list = cdc_frames
        nontarget_frames_list = uart_frames
        target_end, target_start_snap = cdc_end, cdc_start
        nontarget_end, nontarget_start_snap = uart_end, uart_start
        physical_tx_delta = (status_after.cdc_errors -
                             status_before.cdc_errors)

    model = LiveAcceptance(
        live_target=target,
        target_frames=len(target_frames_list),
        nontarget_frames=len(nontarget_frames_list),
        max_sequence_lag=max_lag,
        target_crc_errors=_parser_delta(target_end, target_start_snap, "crc_errors"),
        nontarget_crc_errors=_parser_delta(nontarget_end, nontarget_start_snap,
                                           "crc_errors"),
        header_errors=_parser_delta(target_end, target_start_snap, "header_errors"),
        length_errors=_parser_delta(target_end, target_start_snap, "length_errors"),
        payload_errors=_parser_delta(target_end, target_start_snap, "payload_errors"),
        physical_tx_error_delta=physical_tx_delta,
        drops_iis_delta=state_during["drops_iis"] - state_before["drops_iis"],
        drops_jy_delta=state_during["drops_jy"] - state_before["drops_jy"],
        source_drop_delta=status_after.source_drops - status_before.source_drops,
        stop_latency_s=stop_latency,
        post_stop_sensor_frames=post_stop_frames,
        nontarget_at_probe=nontarget_at_ok,
    )
    types = {frame.message_type for frame in target_frames_list}
    uuids = {str(frame.device_uuid) for frame in target_frames_list}
    passed = (model.passed and types == _SENSOR_TYPES
              and uuids == {state_before["uuid"]})
    return {"passed": passed, "acceptance": dataclasses.asdict(model),
            "sensor_types": sorted(item.name for item in types),
            "observed_uuids": sorted(uuids),
            "nontarget_at_probe_pre_start": nontarget_at_pre,
            "nontarget_at_probe_midstream": nontarget_at_midstream,
            "control_poll_failures": poll_failures}


def _run_overwrite(session: AcceptanceSession) -> dict[str, Any]:
    """C3: BUFFER_FULL does not stop acquisition; remained_acquiring must hold."""
    session.command("AT+SDCLEAR=CONFIRM", timeout_s=5.0)
    session.command("AT+LIVESTREAM=UART")
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


def _run_uuid_persistence(session: AcceptanceSession) -> dict[str, Any]:
    """Three-phase UUID derivation/persistence acceptance across TWO cold boots.

    MJ-E: Goal evidence item 6 requires that the *derived* UUID is stable across
    two cold boots (derivation-algorithm determinism).  That is only provable if
    phase 1 does NOT write the UUID; writing it immediately would make phase 2
    compare a persisted value rather than a freshly re-derived one.

    Phase 1 (record):     uuid_source==DERIVED and no baseline -> record the
                          derived UUID + baud (+ generated_utc/uptime_us) to the
                          baseline and prompt a power cycle.  DO NOT write UUID.
    Phase 2 (derived):    still DERIVED with a baseline -> assert UUID and baud
                          match the baseline across the cold boot (evidence 6),
                          record phase-2 generated_utc/uptime_us, THEN write
                          AT+UUID=<derived> and AT+LIVESTREAM=CDC and prompt a
                          second power cycle.
    Phase 3 (configured): CONFIGURED with a baseline -> assert uuid_configured,
                          baud_stable and livestream_reverted_to_uart (evidence
                          7/8).  On success consume/clean the baseline (MN-2).

    Both cold boots are evidenced by generated_utc and uptime_us (uptime resets
    to a small value after a real power cycle).
    """
    state = session.state()
    status = session.status()
    livestream_reply = session.command("AT+LIVESTREAM?", "+LIVESTREAM:")
    livestream_match = _LIVESTREAM_PATTERN.search(livestream_reply)
    livestream_target = livestream_match.group(1) if livestream_match else ""
    baud_reply = session.command("AT+BAUD?", "+BAUD:")
    baud_match = _BAUD_PATTERN.search(baud_reply)
    current_baud = int(baud_match.group(1)) if baud_match else 0
    generated_utc = datetime.now(timezone.utc).isoformat()
    uptime_us = int(getattr(status, "uptime_us", 0)) if status is not None else 0

    baseline_path = session.arguments.output.with_suffix(".uuid_baseline.json")
    baseline: dict[str, Any] | None = None
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    def _write_baseline(data: dict[str, Any]) -> None:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    if state["uuid_source"] == "DERIVED" and baseline is None:
        # Phase 1: record derived UUID/baud only; never write the UUID here so
        # phase 2 can prove the derivation is stable across a cold boot.
        baseline_data = {
            "uuid": state["uuid"],
            "baud": current_baud,
            "phase1": {"generated_utc": generated_utc, "uptime_us": uptime_us},
        }
        _write_baseline(baseline_data)
        return {
            "passed": True,
            "phase": "record",
            "evidence": [],
            "instruction": "已记录派生 UUID 与 baud 到 baseline（未写入 UUID）。"
                           "请给设备完全断电再上电（冷启动），然后重新运行 "
                           "--mode uuid-persistence 进入阶段2。",
            "baseline": baseline_data,
            "state": state,
        }

    if state["uuid_source"] == "DERIVED" and baseline is not None:
        # Phase 2: still DERIVED after a cold boot -> derivation determinism.
        uuid_stable = state["uuid"] == baseline["uuid"]
        baud_stable = current_baud == baseline["baud"]
        baseline["phase2"] = {"generated_utc": generated_utc,
                              "uptime_us": uptime_us}
        if not (uuid_stable and baud_stable):
            _write_baseline(baseline)
            return {
                "passed": False,
                "phase": "derived",
                "evidence": [],
                "uuid_stable_across_cold_boot": uuid_stable,
                "baud_stable_across_cold_boot": baud_stable,
                "reason": "派生 UUID 或 baud 跨冷启动不一致（证据项6失败）",
                "baseline": baseline,
                "state": state,
            }
        # Derivation proven stable across the cold boot; now persist it and
        # select CDC so phase 3 can verify CONFIGURED + LIVESTREAM revert.
        session.command(f"AT+UUID={state['uuid']}")
        session.command("AT+LIVESTREAM=CDC")
        verify = session.state()
        _write_baseline(baseline)
        return {
            "passed": verify["uuid_source"] == "CONFIGURED"
                      and verify["live_target"] == "CDC",
            "phase": "derived",
            "evidence": ["6:两次冷启动派生UUID稳定"],
            "uuid_stable_across_cold_boot": uuid_stable,
            "baud_stable_across_cold_boot": baud_stable,
            "instruction": "已验证派生 UUID 跨冷启动稳定（证据项6），并写入 "
                           "AT+UUID + AT+LIVESTREAM=CDC。请再次完全断电再上电，"
                           "然后重新运行 --mode uuid-persistence 进入阶段3。",
            "baseline": baseline,
            "state": verify,
        }

    if state["uuid_source"] == "CONFIGURED" and baseline is not None:
        # Phase 3: persisted CONFIGURED across the second cold boot.
        uuid_stable = state["uuid"] == baseline["uuid"]
        baud_stable = current_baud == baseline["baud"]
        livestream_reverted = livestream_target == "UART"  # volatile cold-boot default
        configured = state["uuid_source"] == "CONFIGURED"
        passed = uuid_stable and baud_stable and livestream_reverted and configured
        result = {
            "passed": passed,
            "phase": "configured",
            "evidence": (["7:设置UUID后冷启动仍CONFIGURED且波特率不变",
                          "8:LIVESTREAM=CDC后冷启动恢复UART"] if passed else []),
            "uuid_configured": configured,
            "uuid_stable": uuid_stable,
            "baud_stable": baud_stable,
            "livestream_reverted_to_uart": livestream_reverted,
            "baseline": baseline,
            "phase3": {"generated_utc": generated_utc, "uptime_us": uptime_us},
            "state": state,
        }
        if passed:
            # MN-2: consume the baseline so a re-run cannot reuse a stale base.
            baseline_path.unlink(missing_ok=True)
            result["baseline_consumed"] = True
        return result

    # Fallback: already CONFIGURED without a baseline — just verify defaults.
    return {
        "passed": livestream_target == "UART" and state["state"] == "IDLE",
        "phase": "check",
        "state": state,
        "livestream": livestream_target,
        "baud": current_baud,
    }


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
    session.command("AT+LIVESTREAM=UART")
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
    parser.add_argument("--mode", choices=("preflight", "live-uart", "live-cdc",
                                            "overwrite", "uuid-persistence",
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
        "live-uart": lambda session: _run_live(session, "UART"),
        "live-cdc": lambda session: _run_live(session, "CDC"),
        "overwrite": _run_overwrite,
        "uuid-persistence": _run_uuid_persistence,
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
