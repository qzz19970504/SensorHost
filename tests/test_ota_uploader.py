"""Unit tests for the OTA upload state machine against a fake device."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

import pytest

from sensor_host.ota.codec import FrameType, decode_frame
from sensor_host.ota.package import format_crc, format_version, pack_ota
from sensor_host.ota.uploader import (
    OtaUploadCancelled,
    OtaUploadError,
    OtaUploader,
)


def _package(image_size: int = 1200, app_version: str = "1.2.3") -> bytes:
    image = bytes((index * 13 + 5) & 0xFF for index in range(image_size))
    return pack_ota(image=image, app_version=app_version)


class FakeOtaDevice:
    """Model the firmware OTA endpoint: reply lines queued per received frame."""

    def __init__(
        self,
        *,
        max_image: int = 327_680,
        chunk: int = 512,
        app_version: str = "1.2.3",
        image_crc: int = 0,
        commit_result: str = "STAGED",
        drop_first_data_ack: bool = False,
        offset_retry_once: bool = False,
        offset_nack_mismatch: bool = False,
        data_ack_disabled: bool = False,
        data_nack_code: str | None = None,
    ) -> None:
        self._replies: deque[bytes] = deque()
        self.sent_frames: list = []
        self.sent_raw: list[bytes] = []
        self.max_image = max_image
        self.chunk = chunk
        self.commit_result = commit_result
        self.app_version = app_version
        self.image_crc = image_crc
        self.drop_first_data_ack = drop_first_data_ack
        self.offset_retry_once = offset_retry_once
        self.offset_nack_mismatch = offset_nack_mismatch
        self.data_ack_disabled = data_ack_disabled
        self.data_nack_code = data_nack_code
        self.next_offset = 0
        self._dropped = False
        self._offset_retried = False

    def send(self, data: bytes) -> None:
        self.sent_raw.append(bytes(data))
        if data.startswith(b"AT+OTA"):
            self._replies.append(
                f"+OTA:READY,PROTO=1,MAX={self.max_image},CHUNK={self.chunk}".encode()
            )
            self._replies.append(b"OK")
            return
        frame = decode_frame(data)
        self.sent_frames.append(frame)
        if frame.frame_type is FrameType.BEGIN:
            self._replies.append(b"+OTA:ACK,SEQ=0,NEXT=0")
            return
        if frame.frame_type is FrameType.CANCEL:
            self._replies.append(
                f"+OTA:ACK,SEQ={frame.sequence},NEXT={self.next_offset}".encode()
            )
            return
        if frame.frame_type is FrameType.COMMIT:
            if self.commit_result == "STAGED":
                crc_text = format_crc(self.image_crc)
                self._replies.append(
                    f"+OTA:STAGED,VERSION={self.app_version},CRC={crc_text}".encode()
                )
                self._replies.append(b"OK")
            else:
                self._replies.append(
                    f"+OTA:NACK,CODE={self.commit_result},"
                    f"SEQ={frame.sequence},NEXT={self.next_offset}".encode()
                )
            return
        self._handle_data(frame)

    def _handle_data(self, frame) -> None:
        if self.data_ack_disabled:
            # Never acknowledge DATA: forces the uploader to exhaust retries.
            return
        if self.offset_nack_mismatch:
            # OFFSET NACK whose NEXT disagrees with the sent offset must abort.
            self._replies.append(
                f"+OTA:NACK,CODE=OFFSET,SEQ={frame.sequence},"
                f"NEXT={frame.offset + 4096}".encode()
            )
            return
        if self.data_nack_code is not None:
            self._replies.append(
                f"+OTA:NACK,CODE={self.data_nack_code},"
                f"SEQ={frame.sequence},NEXT={self.next_offset}".encode()
            )
            return
        if frame.offset < self.next_offset:
            # Idempotent duplicate: ACK without advancing NEXT.
            self._replies.append(
                f"+OTA:ACK,SEQ={frame.sequence},NEXT={self.next_offset}".encode()
            )
            return
        if frame.offset > self.next_offset:
            self._replies.append(
                f"+OTA:NACK,CODE=OFFSET,SEQ={frame.sequence},"
                f"NEXT={self.next_offset}".encode()
            )
            return
        if self.offset_retry_once and not self._offset_retried:
            self._offset_retried = True
            self._replies.append(
                f"+OTA:NACK,CODE=OFFSET,SEQ={frame.sequence},"
                f"NEXT={frame.offset}".encode()
            )
            return
        # Accept the frame and advance the durable offset.
        self.next_offset += len(frame.payload)
        if self.drop_first_data_ack and not self._dropped:
            self._dropped = True
            return
        self._replies.append(
            f"+OTA:ACK,SEQ={frame.sequence},NEXT={self.next_offset}".encode()
        )

    def readline(self, timeout: float) -> bytes | None:
        if self._replies:
            return self._replies.popleft()
        return None


def test_happy_path_streams_and_stages() -> None:
    package = _package()
    image_crc = int.from_bytes(package[52:56], "little")
    device = FakeOtaDevice(app_version="1.2.3", image_crc=image_crc)
    progress: list[tuple[int, int, str]] = []

    result = OtaUploader().upload(
        package=package,
        transport=device,
        progress=lambda sent, total, phase: progress.append((sent, total, phase)),
    )

    assert result["staged_version"] == "1.2.3"
    assert result["staged_crc"] == image_crc
    assert result["image_size"] == len(package) - 512
    assert device.next_offset == len(package) - 512
    assert progress[-1][2] == "STAGED"
    assert progress[-1][0] == len(package) - 512
    assert any(phase == "DATA" for _s, _t, phase in progress)
    data_frames = [f for f in device.sent_frames if f.frame_type is FrameType.DATA]
    assert all(len(f.payload) <= 512 for f in data_frames)


def test_lost_ack_is_retried_and_treated_as_idempotent() -> None:
    package = _package(image_size=1024)
    image_crc = int.from_bytes(package[52:56], "little")
    device = FakeOtaDevice(image_crc=image_crc, drop_first_data_ack=True)

    result = OtaUploader().upload(package=package, transport=device)

    assert result["image_size"] == 1024
    # The first DATA frame was sent twice (once lost, once idempotent duplicate).
    first_offset_sends = [
        f for f in device.sent_frames if f.frame_type is FrameType.DATA and f.offset == 0
    ]
    assert len(first_offset_sends) == 2


def test_matching_offset_nack_is_retried() -> None:
    package = _package(image_size=512)
    image_crc = int.from_bytes(package[52:56], "little")
    device = FakeOtaDevice(image_crc=image_crc, offset_retry_once=True)

    result = OtaUploader(max_retries=3).upload(package=package, transport=device)

    assert result["image_size"] == 512
    assert device._offset_retried is True


def test_mismatched_offset_nack_aborts() -> None:
    package = _package(image_size=512)
    device = FakeOtaDevice(offset_nack_mismatch=True)

    with pytest.raises(OtaUploadError) as excinfo:
        OtaUploader().upload(package=package, transport=device)

    assert excinfo.value.code == "OFFSET"


def test_commit_image_crc_nack_aborts() -> None:
    package = _package(image_size=512)
    device = FakeOtaDevice(commit_result="IMAGE_CRC")

    with pytest.raises(OtaUploadError) as excinfo:
        OtaUploader().upload(package=package, transport=device)

    assert excinfo.value.code == "IMAGE_CRC"


def test_data_nack_timeout_aborts() -> None:
    package = _package(image_size=512)
    device = FakeOtaDevice(data_nack_code="TIMEOUT")

    with pytest.raises(OtaUploadError) as excinfo:
        OtaUploader().upload(package=package, transport=device)

    assert excinfo.value.code == "TIMEOUT"


def test_ack_retries_are_exhausted() -> None:
    package = _package(image_size=512)
    device = FakeOtaDevice(data_ack_disabled=True)

    with pytest.raises(OtaUploadError) as excinfo:
        OtaUploader(max_retries=2, ack_timeout=0.01).upload(
            package=package, transport=device
        )

    assert excinfo.value.code == "TIMEOUT"
    data_sends = [f for f in device.sent_frames if f.frame_type is FrameType.DATA]
    assert len(data_sends) == 3  # max_retries + 1 attempts


def test_cancel_sends_cancel_frame_and_raises() -> None:
    package = _package(image_size=2048)
    image_crc = int.from_bytes(package[52:56], "little")
    device = FakeOtaDevice(image_crc=image_crc)
    cancel = {"armed": False}

    def progress(sent: int, total: int, phase: str) -> None:
        if phase == "DATA" and sent >= 512:
            cancel["armed"] = True

    uploader = OtaUploader(cancel_requested=lambda: cancel["armed"])
    with pytest.raises(OtaUploadCancelled):
        uploader.upload(package=package, transport=device, progress=progress)

    assert any(f.frame_type is FrameType.CANCEL for f in device.sent_frames)


def test_image_larger_than_device_max_is_rejected() -> None:
    package = _package(image_size=2048)
    device = FakeOtaDevice(max_image=1024)

    with pytest.raises(OtaUploadError, match="exceeds device maximum"):
        OtaUploader().upload(package=package, transport=device)


def test_source_rejection_is_reported() -> None:
    package = _package(image_size=512)

    class SourceRejectDevice:
        def __init__(self) -> None:
            self._replies = deque([b"ERROR:SOURCE"])

        def send(self, data: bytes) -> None:
            return None

        def readline(self, timeout: float) -> bytes | None:
            return self._replies.popleft() if self._replies else None

    with pytest.raises(OtaUploadError) as excinfo:
        OtaUploader().upload(package=package, transport=SourceRejectDevice())

    assert excinfo.value.code == "SOURCE"


def test_version_and_crc_formatting_matches_firmware_text() -> None:
    package = _package(app_version="2.0.5")
    manifest_version = int.from_bytes(package[40:44], "little")
    manifest_crc = int.from_bytes(package[52:56], "little")

    assert format_version(manifest_version) == "2.0.5"
    assert format_crc(manifest_crc) == f"{manifest_crc:08X}"
