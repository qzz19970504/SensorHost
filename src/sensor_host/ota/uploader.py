"""Host-side OTA upload state machine: handshake, stream, commit, cancel.

The uploader is Qt-free and transport-agnostic.  It drives a stop-and-wait
exchange over an :class:`UploadTransport` (``send``/``readline``), mirroring
the firmware contract: ``AT+OTA=BEGIN`` handshake, a BEGIN frame carrying the
first 80 manifest bytes, contiguous DATA frames of at most 512 bytes, then a
COMMIT.  Duplicate frames are idempotent, a matching ``NACK,CODE=OFFSET`` is
retried, every other NACK aborts immediately, and a cooperative cancel sends a
CANCEL frame before raising.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from sensor_host.ota.codec import (
    BEGIN_PAYLOAD_SIZE,
    FRAME_MAX_PAYLOAD,
    DeviceResponse,
    FrameType,
    OtaCodecError,
    UploadFrame,
    encode_frame,
    parse_ready,
    parse_response,
)
from sensor_host.ota.package import (
    MANIFEST_BLOCK_SIZE,
    TARGET_ID,
    format_crc,
    format_version,
    validate_package,
)


BEGIN_COMMAND = b"AT+OTA=BEGIN\r\n"

PHASE_HANDSHAKE = "HANDSHAKE"
PHASE_BEGIN = "BEGIN"
PHASE_DATA = "DATA"
PHASE_COMMIT = "COMMIT"
PHASE_STAGED = "STAGED"


class OtaUploadError(RuntimeError):
    """Report a failed OTA upload with firmware-aligned context."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class OtaUploadCancelled(OtaUploadError):
    """Report a cooperative user cancellation of an in-flight upload."""


class UploadTransport(Protocol):
    """Send raw upstream bytes and read one downstream OTA reply line."""

    def send(self, data: bytes) -> None:
        """Write raw bytes (an OTAF frame or the ASCII begin command)."""

    def readline(self, timeout: float) -> bytes | None:
        """Return the next complete ``+OTA:``/``OK`` line, or None on timeout."""


ProgressCallback = Callable[[int, int, str], None]


class OtaUploader:
    """Drive one full OTA upload with retries, idempotency and cancellation."""

    def __init__(
        self,
        *,
        max_retries: int = 5,
        ack_timeout: float = 2.0,
        commit_timeout: float = 30.0,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if ack_timeout <= 0.0:
            raise ValueError("ack_timeout must be positive")
        if commit_timeout <= 0.0:
            raise ValueError("commit_timeout must be positive")
        self.max_retries = max_retries
        self.ack_timeout = ack_timeout
        self.commit_timeout = commit_timeout
        self.cancel_requested = cancel_requested

    def upload(
        self,
        *,
        package: bytes,
        transport: UploadTransport,
        progress: ProgressCallback | None = None,
        expected_target_id: bytes = TARGET_ID,
    ) -> dict[str, Any]:
        """Run the whole upload and return the staged summary on success."""
        manifest = validate_package(package)
        if manifest["target_id"] != expected_target_id:
            raise OtaUploadError(
                "OTA package target does not match the device", code="TARGET"
            )
        image = package[MANIFEST_BLOCK_SIZE:]
        manifest_block = package[:MANIFEST_BLOCK_SIZE]
        image_size = len(image)

        self._notify(progress, 0, image_size, PHASE_HANDSHAKE)
        max_image, chunk = self._handshake(transport)
        if image_size > max_image:
            raise OtaUploadError(
                f"image size {image_size} exceeds device maximum {max_image}"
            )
        payload_limit = min(FRAME_MAX_PAYLOAD, chunk) if chunk else FRAME_MAX_PAYLOAD
        if payload_limit <= 0:
            raise OtaUploadError("device advertised an invalid chunk size")

        self._notify(progress, 0, image_size, PHASE_BEGIN)
        begin = UploadFrame(FrameType.BEGIN, 0, 0, manifest_block[:BEGIN_PAYLOAD_SIZE])
        response = self._exchange(transport, begin, self.ack_timeout)
        if response.next_offset != 0:
            raise OtaUploadError("device acknowledged a non-zero BEGIN offset")

        self._notify(progress, 0, image_size, PHASE_DATA)
        sequence = 1
        offset = 0
        while offset < image_size:
            self._check_cancelled(transport, sequence, offset)
            chunk_bytes = image[offset : offset + payload_limit]
            frame = UploadFrame(FrameType.DATA, sequence, offset, chunk_bytes)
            response = self._exchange(transport, frame, self.ack_timeout)
            if response.next_offset != offset + len(chunk_bytes):
                raise OtaUploadError(
                    f"device acknowledged unexpected offset {response.next_offset}"
                )
            offset = response.next_offset
            sequence = (sequence + 1) & 0xFFFFFFFF
            self._notify(progress, offset, image_size, PHASE_DATA)

        self._notify(progress, image_size, image_size, PHASE_COMMIT)
        self._check_cancelled(transport, sequence, offset)
        commit = UploadFrame(FrameType.COMMIT, sequence, offset, b"")
        response = self._exchange(transport, commit, self.commit_timeout)
        if not response.staged:
            raise OtaUploadError(
                "device did not stage the image after COMMIT", code=response.code
            )
        # Consume the trailing OK that follows +OTA:STAGED so the reply queue
        # is left clean; the device resets immediately afterwards.
        transport.readline(self.ack_timeout)
        self._notify(progress, image_size, image_size, PHASE_STAGED)
        return {
            "staged_version": response.version,
            "staged_crc": response.crc,
            "app_version": manifest["app_version"],
            "app_version_text": format_version(int(manifest["app_version"])),
            "image_crc32": manifest["image_crc32"],
            "image_crc_text": format_crc(int(manifest["image_crc32"])),
            "image_size": image_size,
            "package_id": manifest["package_id"],
        }

    def cancel(self, transport: UploadTransport, sequence: int, offset: int) -> None:
        """Send one CANCEL frame, ignoring any reply (session teardown)."""
        try:
            transport.send(
                encode_frame(UploadFrame(FrameType.CANCEL, sequence, offset, b""))
            )
        except (OtaCodecError, OSError, RuntimeError):
            pass

    def _handshake(self, transport: UploadTransport) -> tuple[int, int]:
        self._check_cancelled(transport, 0, 0)
        transport.send(BEGIN_COMMAND)
        ready_line = transport.readline(self.ack_timeout)
        if ready_line is None:
            raise OtaUploadError("device did not answer AT+OTA=BEGIN")
        if not ready_line.strip().startswith(b"+OTA:READY,"):
            text = ready_line.decode("ascii", errors="replace").strip()
            if text.startswith("ERROR:SOURCE"):
                raise OtaUploadError(
                    "OTA is only allowed from a UART-source link (Wi-Fi gateway)",
                    code="SOURCE",
                )
            raise OtaUploadError(f"device did not enter OTA mode: {text!r}")
        max_image, chunk = parse_ready(ready_line)
        ok_line = transport.readline(self.ack_timeout)
        if ok_line is None or ok_line.strip() != b"OK":
            raise OtaUploadError("device READY handshake did not complete")
        return max_image, chunk

    def _exchange(
        self,
        transport: UploadTransport,
        frame: UploadFrame,
        timeout: float,
    ) -> DeviceResponse:
        encoded = encode_frame(frame)
        for _ in range(self.max_retries + 1):
            self._check_cancelled(transport, frame.sequence, frame.offset)
            transport.send(encoded)
            response_line = transport.readline(timeout)
            if response_line is None:
                continue
            try:
                response = parse_response(response_line)
            except OtaCodecError as error:
                raise OtaUploadError(str(error)) from error
            if response.acknowledged:
                return response
            if response.code == "OFFSET" and response.next_offset == frame.offset:
                continue
            raise OtaUploadError(
                f"device rejected {frame.frame_type.name}: "
                f"{response.code} seq={response.sequence} next={response.next_offset}",
                code=response.code,
            )
        raise OtaUploadError(
            f"timeout waiting for {frame.frame_type.name} acknowledgement",
            code="TIMEOUT",
        )

    def _check_cancelled(
        self, transport: UploadTransport, sequence: int, offset: int
    ) -> None:
        if self.cancel_requested is not None and self.cancel_requested():
            self.cancel(transport, sequence, offset)
            raise OtaUploadCancelled("upload cancelled")

    @staticmethod
    def _notify(
        progress: ProgressCallback | None,
        sent_bytes: int,
        total_bytes: int,
        phase: str,
    ) -> None:
        if progress is not None:
            progress(sent_bytes, total_bytes, phase)
