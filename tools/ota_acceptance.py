"""STM32 SD-staged OTA acceptance gate for the sensor host.

Self-contained host-side counterpart to the firmware repo's
``tools/ota_bench_gate.py``: it drives the same negative (tampered image CRC)
and positive (clean image) OTA paths, but reuses ``sensor_host.ota`` and never
imports the firmware repository.  Two physical links are supported:

* ESP32 UART bridge over TCP  ``--tcp-listen 54321 --wake-udp <esp32>:12345``
  with an optional read-only CDC ``--state-port`` for AT+STATE? while the OTA
  session owns USART2, and
* a bench split serial pair    ``--command-port COM12 --response-port COM19``.

Evidence is written as JSON (``--report``) for ``docs/validation``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

HOST_SOURCE = Path(__file__).resolve().parents[1] / "src"
if str(HOST_SOURCE) not in sys.path:
    sys.path.insert(0, str(HOST_SOURCE))

from sensor_host.ota import (  # noqa: E402
    FRAME_MAX_PAYLOAD,
    FrameType,
    OtaUploadError,
    StreamDemultiplexer,
    UploadFrame,
    encode_frame,
    format_crc,
    load_package,
    parse_response,
)


class SerialEndpoints:
    """Bench split: commands on one UART, replies read from a second port."""

    def __init__(self, command_port: str, response_port: str, baud: int) -> None:
        import serial

        self.command = serial.Serial(command_port, baud, timeout=0.2)
        self.response = serial.Serial(response_port, baud, timeout=0.2)
        time.sleep(0.4)
        self.reset_input()

    def reset_input(self) -> None:
        self.response.reset_input_buffer()

    def send(self, data: bytes) -> None:
        self.command.write(data)
        self.command.flush()

    def read(self, size: int) -> bytes:
        return self.response.read(size)

    def state_send(self, data: bytes) -> None:
        self.response.reset_input_buffer()
        self.response.write(data)
        self.response.flush()

    def state_read(self, size: int) -> bytes:
        return self.response.read(size)

    def close(self) -> None:
        self.command.close()
        self.response.close()


class TcpEndpoints:
    """Production path: one full-duplex TCP stream to the ESP32 UART bridge."""

    WAKE_PAYLOAD = b"TCPCONNECT"

    def __init__(
        self,
        port: int,
        bind_host: str,
        wake_target: str,
        accept_timeout: float,
        state_port: str | None,
        state_baud: int,
    ) -> None:
        import socket
        import threading

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((bind_host, port))
        self.socket.listen(1)
        self.socket.settimeout(accept_timeout)
        self._wake_stop = threading.Event()
        wake = threading.Thread(
            target=self._wake_loop, args=(wake_target,), daemon=True
        )
        wake.start()
        self.connection, self.peer = self.socket.accept()
        self._wake_stop.set()
        self.connection.settimeout(0.2)
        self.state = None
        if state_port is not None:
            import serial

            self.state = serial.Serial(state_port, state_baud, timeout=0.2)
        time.sleep(0.3)
        self.reset_input()

    def _wake_loop(self, wake_target: str) -> None:
        import socket

        if not wake_target:
            return
        host, _, port_text = wake_target.partition(":")
        try:
            port = int(port_text)
        except ValueError:
            return
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while not self._wake_stop.is_set():
            try:
                sender.sendto(self.WAKE_PAYLOAD, (host, port))
            except OSError:
                pass
            self._wake_stop.wait(3.0)
        sender.close()

    def reset_input(self) -> None:
        self.connection.settimeout(0.05)
        try:
            while self.connection.recv(4096):
                pass
        except OSError:
            pass
        self.connection.settimeout(0.2)

    def send(self, data: bytes) -> None:
        self.connection.sendall(data)

    def read(self, size: int) -> bytes:
        try:
            return self.connection.recv(size)
        except (OSError, TimeoutError):
            return b""

    def state_send(self, data: bytes) -> None:
        if self.state is not None:
            self.state.reset_input_buffer()
            self.state.write(data)
            self.state.flush()
            return
        self.send(data)

    def state_read(self, size: int) -> bytes:
        if self.state is not None:
            return self.state.read(size)
        return self.read(size)

    def close(self) -> None:
        try:
            self.connection.close()
        except OSError:
            pass
        self.socket.close()
        if self.state is not None:
            self.state.close()


class BenchLink:
    """Demultiplex one bidirectional OTA stream into +OTA lines and state."""

    def __init__(self, endpoints, guard_ms: float = 250.0,
                 frame_guard_ms: float = 30.0) -> None:
        self.endpoints = endpoints
        self.guard_ms = guard_ms
        self.frame_guard_ms = frame_guard_ms
        self._demux = StreamDemultiplexer()
        self._lines: deque[bytes] = deque()

    def close(self) -> None:
        self.endpoints.close()

    def send(self, data: bytes) -> None:
        self.endpoints.send(data)

    def readline(self, timeout: float) -> bytes | None:
        """Return the next bare +OTA:/OK line, feeding the demultiplexer."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._lines:
                return self._lines.popleft()
            chunk = self.endpoints.read(4096)
            if chunk:
                ota_lines, _parser_bytes = self._demux.feed(chunk)
                self._lines.extend(ota_lines)
            else:
                time.sleep(0.01)
        return None

    def guard(self, milliseconds: float) -> None:
        if milliseconds > 0:
            time.sleep(milliseconds / 1000.0)

    def state_field(self, prefix: bytes, timeout: float = 2.0) -> bytes:
        self.endpoints.state_send(b"AT+STATE?\r\n")
        deadline = time.time() + timeout
        buffer = b""
        while time.time() < deadline:
            chunk = self.endpoints.state_read(4096)
            if chunk:
                buffer += chunk
            elif buffer:
                break
        for line in buffer.replace(b"\r", b"\n").split(b"\n"):
            if line.strip().startswith(prefix):
                return line.strip()
        raise OtaUploadError(f"no {prefix.decode()} in {buffer!r}")

    def handshake(self, timeout: float) -> str:
        self.endpoints.reset_input()
        self._demux.reset()
        self._lines.clear()
        self.send(b"AT+OTA=BEGIN\r\n")
        ready = self.readline(timeout)
        if ready is None or not ready.startswith(b"+OTA:READY,"):
            raise OtaUploadError(f"unexpected handshake: {ready!r}")
        ok = self.readline(timeout)
        if ok is None or ok.strip() != b"OK":
            raise OtaUploadError("handshake OK line missing")
        self.guard(self.guard_ms)
        return ready.decode()


def stream_image(link: BenchLink, payload: bytes, manifest_block: bytes,
                 timeout: float, max_retries: int) -> tuple[int, int]:
    """Stage every DATA frame; return (next_sequence, image_size)."""
    def exchange(frame: UploadFrame):
        encoded = encode_frame(frame)
        for attempt in range(max_retries + 1):
            link.send(encoded)
            line = link.readline(timeout)
            if line is not None:
                return parse_response(line)
            if attempt >= max_retries:
                raise OtaUploadError(f"no reply for {frame.frame_type.name}")
            link.guard(link.frame_guard_ms)
        raise OtaUploadError(f"timeout on {frame.frame_type.name}")

    response = exchange(UploadFrame(FrameType.BEGIN, 0, 0, manifest_block[:80]))
    if not response.acknowledged:
        raise OtaUploadError(f"BEGIN rejected: {response}")
    link.guard(link.frame_guard_ms)
    sequence = 1
    offset = 0
    while offset < len(payload):
        chunk = payload[offset:offset + FRAME_MAX_PAYLOAD]
        response = exchange(UploadFrame(FrameType.DATA, sequence, offset, chunk))
        if not response.acknowledged or response.next_offset != offset + len(chunk):
            raise OtaUploadError(f"DATA rejected at {offset}: {response}")
        offset = response.next_offset
        sequence = (sequence + 1) & 0xFFFFFFFF
        link.guard(link.frame_guard_ms)
    return sequence, offset


def commit(link: BenchLink, sequence: int, offset: int, timeout: float) -> bytes:
    link.send(encode_frame(UploadFrame(FrameType.COMMIT, sequence, offset, b"")))
    line = link.readline(timeout)
    if line is None:
        raise OtaUploadError("no COMMIT reply")
    return line


def cancel(link: BenchLink, sequence: int, offset: int, timeout: float) -> None:
    link.send(encode_frame(UploadFrame(FrameType.CANCEL, sequence, offset, b"")))
    response = parse_response(link.readline(timeout) or b"")
    if not response.acknowledged:
        raise OtaUploadError(f"CANCEL rejected: {response}")
    link.guard(link.guard_ms)


def run_negative(link: BenchLink, package, timeout: float, commit_timeout: float,
                 retries: int) -> dict:
    manifest_block = package.manifest_block
    tampered = bytearray(package.image)
    tampered[-1] ^= 0x5A
    before = link.state_field(b"+OTA:").decode()
    link.handshake(timeout)
    sequence, offset = stream_image(
        link, bytes(tampered), manifest_block, timeout, retries
    )
    reply = commit(link, sequence, offset, commit_timeout)
    response = parse_response(reply)
    after = link.state_field(b"+OTA:").decode()
    cancel(link, sequence + 1, offset, timeout)
    if response.acknowledged or response.code != "IMAGE_CRC":
        raise OtaUploadError(f"expected IMAGE_CRC NACK, got {reply!r}")
    if b"RECEIVING" not in after.encode():
        raise OtaUploadError(f"session did not stay RECEIVING: {after}")
    return {"commit_reply": reply.decode(), "before": before, "after": after}


def run_positive(link: BenchLink, package, timeout: float, commit_timeout: float,
                 retries: int) -> dict:
    link.handshake(timeout)
    sequence, offset = stream_image(
        link, package.image, package.manifest_block, timeout, retries
    )
    reply = commit(link, sequence, offset, commit_timeout)
    if b"+OTA:STAGED" not in reply:
        raise OtaUploadError(f"expected STAGED, got {reply!r}")
    ok = link.readline(timeout)
    if ok is None or ok.strip() != b"OK":
        raise OtaUploadError("STAGED OK line missing")
    response = parse_response(reply)
    if response.crc != package.image_crc32:
        raise OtaUploadError(
            f"staged CRC {format_crc(response.crc or 0)} != package "
            f"{package.crc_text}"
        )
    return {"staged": reply.decode(), "crc": format_crc(response.crc or 0),
            "version": response.version}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="path to app.ota")
    parser.add_argument("--command-port")
    parser.add_argument("--response-port")
    parser.add_argument("--baud", type=int, default=460800)
    parser.add_argument("--tcp-listen", type=int)
    parser.add_argument("--tcp-bind", default="0.0.0.0")
    parser.add_argument("--wake-udp", default="192.168.137.255:12345")
    parser.add_argument("--accept-timeout", type=float, default=60.0)
    parser.add_argument("--state-port")
    parser.add_argument("--state-baud", type=int, default=460800)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--commit-timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--guard-ms", type=float, default=250.0)
    parser.add_argument("--frame-guard-ms", type=float, default=30.0)
    parser.add_argument("--report", help="write JSON evidence to this path")
    args = parser.parse_args()

    if not args.tcp_listen and not (args.command_port and args.response_port):
        parser.error(
            "--tcp-listen, or --command-port with --response-port, is required"
        )

    package = load_package(args.input)
    if args.tcp_listen:
        endpoints = TcpEndpoints(
            port=args.tcp_listen,
            bind_host=args.tcp_bind,
            wake_target=args.wake_udp,
            accept_timeout=args.accept_timeout,
            state_port=args.state_port,
            state_baud=args.state_baud,
        )
    else:
        endpoints = SerialEndpoints(
            args.command_port, args.response_port, args.baud
        )
    link = BenchLink(endpoints, guard_ms=args.guard_ms,
                     frame_guard_ms=args.frame_guard_ms)
    report = {
        "input": str(args.input),
        "package_version": package.version_text,
        "package_crc": package.crc_text,
        "image_size": package.image_size,
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        print("[1/2] negative path: tampered image must never reach READY")
        report["negative"] = run_negative(
            link, package, args.timeout, args.commit_timeout, args.retries
        )
        print(f"  commit -> {report['negative']['commit_reply']}")
        print("[2/2] positive path: clean image reaches STAGED")
        report["positive"] = run_positive(
            link, package, args.timeout, args.commit_timeout, args.retries
        )
        print(f"  staged -> {report['positive']['staged']}")
        report["result"] = "PASS"
    except OtaUploadError as error:
        report["result"] = "FAIL"
        report["error"] = str(error)
        print(f"acceptance FAILED: {error}", file=sys.stderr)
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        link.close()
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"report written to {report_path}")
    return 0 if report.get("result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
