"""Timed end-to-end CDC recording and replay acceptance runner."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sensor_host.protocol import MessageType, StatusV1, StreamParser
from sensor_host.storage import RawSessionRecorder, replay_chunks
from sensor_host.tools import AcceptanceReport
from sensor_host.transport import CdcSerialTransport


_READ_BYTES = 65_536
_READ_TIMEOUT_S = 0.05
_STATUS_INTERVAL_S = 5.0
_FINAL_STATUS_TIMEOUT_S = 2.0


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _counter_delta(final: int, baseline: int) -> int:
    """Firmware counters saturate, so a backwards value is invalid, not wrap."""
    return final - baseline if final >= baseline else 2**32


def _feed(parser: StreamParser, chunk: bytes) -> tuple[StatusV1 | None, int]:
    latest_status = None
    jy61pl_frames = 0
    for frame in parser.feed(chunk):
        if frame.message_type is MessageType.STATUS and frame.status is not None:
            latest_status = frame.status
        elif frame.message_type is MessageType.JY61PL_SAMPLE:
            jy61pl_frames += 1
    return latest_status, jy61pl_frames


def _warm_up(
    transport: CdcSerialTransport,
    duration_s: float,
) -> StatusV1:
    parser = StreamParser()
    latest_status = None
    # C4: Cold-boot default is LIVESTREAM=UART; must select CDC before START
    # so that CDC receives active sensor frames.
    transport.write_control(b"AT+LIVESTREAM=CDC")
    transport.write_control(b"AT+START")
    transport.write_control(b"AT+STATE?")
    transport.write_control(b"status")
    deadline = time.monotonic() + duration_s
    next_status_s = time.monotonic() + min(_STATUS_INTERVAL_S, duration_s)
    while time.monotonic() < deadline:
        now_s = time.monotonic()
        if now_s >= next_status_s:
            transport.write_control(b"status")
            next_status_s = now_s + _STATUS_INTERVAL_S
        status, _jy_frames = _feed(
            parser,
            transport.read(_READ_BYTES, _READ_TIMEOUT_S),
        )
        if status is not None:
            latest_status = status
    transport.write_control(b"status")
    status_deadline = time.monotonic() + _FINAL_STATUS_TIMEOUT_S
    while latest_status is None and time.monotonic() < status_deadline:
        status, _jy_frames = _feed(
            parser,
            transport.read(_READ_BYTES, _READ_TIMEOUT_S),
        )
        if status is not None:
            latest_status = status
    if latest_status is None:
        raise RuntimeError("firmware did not return a STATUS frame during warmup")
    return latest_status


def run_acceptance(
    port: str,
    duration_s: float,
    output_path: Path,
    watermark: int,
    warmup_s: float,
) -> tuple[AcceptanceReport, StatusV1, StatusV1]:
    """Acquire, record, replay and compare one CDC acceptance session."""
    transport = CdcSerialTransport()
    recorder = RawSessionRecorder()
    recorder_active = False
    transport.open(port)
    try:
        transport.write_control(f"acq watermark {watermark}".encode("ascii"))
        baseline_status = _warm_up(transport, warmup_s)
        if baseline_status.acquisition_state != 1:
            raise RuntimeError(
                "firmware is not running acquisition "
                f"(state={baseline_status.acquisition_state})"
            )
        if baseline_status.watermark_words != watermark:
            raise RuntimeError(
                "firmware did not apply requested watermark "
                f"({baseline_status.watermark_words} != {watermark})"
            )
        live_parser = StreamParser()
        latest_status = baseline_status
        bytes_received = 0
        jy61pl_frames = 0
        recorder.start(
            output_path,
            {
                "transport": "cdc",
                "port": port,
                "watermark_words": watermark,
                "requested_duration_s": duration_s,
            },
        )
        recorder_active = True
        started_s = time.monotonic()
        deadline_s = started_s + duration_s
        next_status_s = started_s + _STATUS_INTERVAL_S
        while time.monotonic() < deadline_s:
            now_s = time.monotonic()
            if now_s >= next_status_s:
                transport.write_control(b"status")
                next_status_s = now_s + _STATUS_INTERVAL_S
            chunk = transport.read(_READ_BYTES, _READ_TIMEOUT_S)
            if not chunk:
                continue
            if not recorder.submit(chunk):
                raise RuntimeError(recorder.failure or "recorder rejected input")
            bytes_received += len(chunk)
            status, jy_count = _feed(live_parser, chunk)
            jy61pl_frames += jy_count
            if status is not None:
                latest_status = status

        previous_status_uptime = latest_status.uptime_us
        transport.write_control(b"status")
        final_deadline_s = time.monotonic() + _FINAL_STATUS_TIMEOUT_S
        while (
            latest_status.uptime_us == previous_status_uptime
            and time.monotonic() < final_deadline_s
        ):
            chunk = transport.read(_READ_BYTES, _READ_TIMEOUT_S)
            if not chunk:
                continue
            if not recorder.submit(chunk):
                raise RuntimeError(recorder.failure or "recorder rejected input")
            bytes_received += len(chunk)
            status, jy_count = _feed(live_parser, chunk)
            jy61pl_frames += jy_count
            if status is not None:
                latest_status = status
        if latest_status.uptime_us == previous_status_uptime:
            raise RuntimeError("firmware did not return the final STATUS frame")

        elapsed_s = time.monotonic() - started_s
        recording_summary = recorder.stop()
        recorder_active = False
        replay_parser = StreamParser()
        for chunk in replay_chunks(output_path):
            replay_parser.feed(chunk)
        report = AcceptanceReport(
            duration_s=elapsed_s,
            bytes_received=bytes_received,
            frames=live_parser.stats.frames,
            crc_errors=live_parser.stats.crc_errors,
            sequence_gaps=live_parser.stats.sequence_gaps,
            source_drop_delta=_counter_delta(
                latest_status.source_drops,
                baseline_status.source_drops,
            ),
            transport_drop_delta=_counter_delta(
                latest_status.transport_drops,
                baseline_status.transport_drops,
            ),
            fifo_overrun_delta=_counter_delta(
                latest_status.fifo_overruns,
                baseline_status.fifo_overruns,
            ),
            recorder_bytes=recording_summary.bytes_written,
            replay_frames=replay_parser.stats.frames,
            jy61pl_frames=jy61pl_frames,
            replay_crc_errors=replay_parser.stats.crc_errors,
            replay_sequence_gaps=replay_parser.stats.sequence_gaps,
        )
        return report, baseline_status, latest_status
    finally:
        if recorder_active:
            recorder.stop()
        try:
            transport.write_control(b"AT+STOP")
            # C4: Restore LIVESTREAM=UART after CDC acceptance
            transport.write_control(b"AT+LIVESTREAM=UART")
        except (OSError, RuntimeError):
            pass
        transport.close()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--duration", type=float, default=1800.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--watermark", type=int, choices=(128, 256, 511), default=256)
    parser.add_argument("--warmup", type=float, default=5.0)
    parser.add_argument("--json-report", type=Path)
    arguments = parser.parse_args()
    if arguments.duration <= 0.0:
        parser.error("--duration must be positive")
    if arguments.warmup < 0.0:
        parser.error("--warmup must not be negative")
    return arguments


def main() -> int:
    arguments = _arguments()
    output_path = arguments.output or (
        Path("host") / "recordings" / f"acceptance-{_utc_stamp()}.sdf1"
    )
    report_path = arguments.json_report or output_path.with_suffix(".acceptance.json")
    try:
        report, baseline_status, final_status = run_acceptance(
            port=arguments.port,
            duration_s=arguments.duration,
            output_path=output_path,
            watermark=arguments.watermark,
            warmup_s=arguments.warmup,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"CDC acceptance failed: {error}", file=sys.stderr)
        return 2
    document = {
        "passed": report.passed,
        "port": arguments.port,
        "recording": str(output_path),
        "report": dataclasses.asdict(report),
        "baseline_status": dataclasses.asdict(baseline_status),
        "final_status": dataclasses.asdict(final_status),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(json.dumps(document, indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
