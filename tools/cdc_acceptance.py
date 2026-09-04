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


_CLI_READ_TIMEOUT_S = 2.0


def _read_cli(
    transport: CdcSerialTransport,
    parser: StreamParser,
    expected: str,
    timeout_s: float = _CLI_READ_TIMEOUT_S,
    tolerate: tuple[str, ...] = (),
) -> str:
    """Read CLI_RESPONSE frames until ``expected`` appears in the text.

    Returns the accumulated CLI text.  Raises RuntimeError on an unexpected
    ``ERROR:`` reply (unless a substring of ``tolerate`` is present) and
    TimeoutError if ``expected`` never arrives.  Unlike a bare write_control,
    this validates the firmware reply so a swallowed ERROR:STATE cannot
    masquerade as success and leave LIVESTREAM unset (R9 -> zero CDC frames).
    """
    collected = ""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for frame in parser.feed(transport.read(_READ_BYTES, _READ_TIMEOUT_S)):
            if frame.message_type is MessageType.CLI_RESPONSE and frame.cli_text:
                collected += frame.cli_text
        if expected in collected:
            return collected
        if "ERROR:" in collected and not any(tok in collected for tok in tolerate):
            raise RuntimeError(f"CDC control replied: {collected.strip()}")
    raise TimeoutError(
        f"timed out waiting for {expected!r}; got {collected.strip()!r}")


def _ensure_idle(
    transport: CdcSerialTransport,
    parser: StreamParser,
    timeout_s: float = 5.0,
) -> bool:
    """R9/N-6: reach IDLE, skipping AT+STOP when the device is already IDLE.

    N-6: query AT+STATE? first; if already IDLE return at once so warm-up and
    restore no longer burn a fixed ~2 s AT+STOP timeout on every round.  Only
    when not IDLE do we issue AT+STOP (tolerating ERROR:STATE) and poll.
    """
    transport.write_control(b"AT+STATE?")
    try:
        reply = _read_cli(transport, parser, "+STATE:")
    except (RuntimeError, TimeoutError):
        reply = ""
    if "+STATE:IDLE" in reply:
        return True
    transport.write_control(b"AT+STOP")
    try:
        _read_cli(transport, parser, "OK", tolerate=("ERROR:STATE",))
    except (RuntimeError, TimeoutError):
        pass
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        transport.write_control(b"AT+STATE?")
        try:
            reply = _read_cli(transport, parser, "+STATE:")
        except (RuntimeError, TimeoutError):
            reply = ""
        if "+STATE:IDLE" in reply:
            return True
        time.sleep(0.1)
    return False


def _set_livestream(
    transport: CdcSerialTransport,
    parser: StreamParser,
    target: str,
    timeout_s: float = 3.0,
    busy_retries: int = 3,
) -> bool:
    """R9/N-6: switch live target in IDLE and validate the set + query reply.

    N-6: AT+LIVESTREAM= is idempotent (re-selecting the current target returns
    OK), so a transient ERROR:BUSY — a live transfer still draining while IDLE —
    is backed off and retried a bounded number of times, aligned with
    AcceptanceSession.command()'s busy-retry policy.
    """
    for attempt in range(busy_retries + 1):
        transport.write_control(f"AT+LIVESTREAM={target}".encode("ascii"))
        try:
            reply = _read_cli(transport, parser, "OK", timeout_s=timeout_s,
                              tolerate=("ERROR:BUSY",))
        except (RuntimeError, TimeoutError):
            return False
        if "ERROR:BUSY" in reply:
            if attempt >= busy_retries:
                return False
            time.sleep(0.5 * (2 ** attempt))
            continue
        if "ERROR:" in reply:
            return False
        transport.write_control(b"AT+LIVESTREAM?")
        try:
            query = _read_cli(transport, parser, "+LIVESTREAM:", timeout_s=timeout_s)
        except (RuntimeError, TimeoutError):
            return False
        return f"+LIVESTREAM:{target}" in query
    return False


def _warm_up(
    transport: CdcSerialTransport,
    duration_s: float,
) -> tuple[StatusV1, dict[str, bool]]:
    parser = StreamParser()
    latest_status = None
    # R9: reach IDLE first, then select CDC and validate the reply.  A bare
    # write_control silently swallows ERROR:STATE, which would leave LIVESTREAM
    # on UART and cause a false "zero CDC frames" acceptance failure.
    idle_ok = _ensure_idle(transport, parser)
    set_cdc_ok = idle_ok and _set_livestream(transport, parser, "CDC")
    handshake = {"idle_before_switch": idle_ok, "livestream_set_cdc_ok": set_cdc_ok}
    if not set_cdc_ok:
        raise RuntimeError(
            f"failed to select LIVESTREAM=CDC in IDLE before START (idle={idle_ok})")
    # C4: Cold-boot default is LIVESTREAM=UART; CDC selected above before START
    # so that CDC receives active sensor frames.
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
    return latest_status, handshake


def run_acceptance(
    port: str,
    duration_s: float,
    output_path: Path,
    watermark: int,
    warmup_s: float,
) -> tuple[AcceptanceReport, StatusV1, StatusV1, dict[str, bool]]:
    """Acquire, record, replay and compare one CDC acceptance session."""
    transport = CdcSerialTransport()
    recorder = RawSessionRecorder()
    recorder_active = False
    control_results: dict[str, bool] = {}
    transport.open(port)
    try:
        transport.write_control(f"acq watermark {watermark}".encode("ascii"))
        baseline_status, handshake = _warm_up(transport, warmup_s)
        control_results.update(handshake)
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
        return report, baseline_status, latest_status, control_results
    finally:
        if recorder_active:
            recorder.stop()
        # R9: restore LIVESTREAM=UART only after reaching IDLE, validating the
        # reply so a swallowed ERROR:STATE is not mistaken for success.
        try:
            restore_parser = StreamParser()
            idle_ok = _ensure_idle(transport, restore_parser)
            control_results["livestream_restore_uart_ok"] = (
                idle_ok and _set_livestream(transport, restore_parser, "UART"))
        except (OSError, RuntimeError, TimeoutError):
            control_results["livestream_restore_uart_ok"] = False
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
        report, baseline_status, final_status, control_results = run_acceptance(
            port=arguments.port,
            duration_s=arguments.duration,
            output_path=output_path,
            watermark=arguments.watermark,
            warmup_s=arguments.warmup,
        )
    except (OSError, RuntimeError, ValueError, TimeoutError) as error:
        print(f"CDC acceptance failed: {error}", file=sys.stderr)
        return 2
    livestream_set_ok = bool(
        control_results.get("livestream_set_cdc_ok")
        and control_results.get("livestream_restore_uart_ok"))
    # Minor-b: if LIVESTREAM=UART could not be restored the device is left
    # streaming to CDC, so the next round's preflight (which expects the
    # cold-boot UART default) would fail.  Warn loudly on stderr AND fold the
    # handshake into the exit code so it cannot slip through as a green run.
    if not control_results.get("livestream_restore_uart_ok"):
        print(
            "WARNING: 恢复 LIVESTREAM=UART 失败——设备可能仍停留在 LIVESTREAM=CDC，"
            "下一轮 preflight 前必须给设备完全断电再上电（冷启动）以恢复 UART 默认。",
            file=sys.stderr,
        )
    document = {
        "passed": report.passed,
        "port": arguments.port,
        "recording": str(output_path),
        "report": dataclasses.asdict(report),
        "baseline_status": dataclasses.asdict(baseline_status),
        "final_status": dataclasses.asdict(final_status),
        "control_results": control_results,
        "livestream_set_ok": livestream_set_ok,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(json.dumps(document, indent=2))
    return 0 if (report.passed and livestream_set_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
