"""AppController OTA lifecycle tests over a scripted Wi-Fi gateway transport."""

from __future__ import annotations

import struct
import threading
import time
import uuid
import zlib
from collections import deque

from sensor_host.ota.codec import FrameType, decode_frame
from sensor_host.ota.package import pack_ota
from sensor_host.presentation.app_controller import AppController
from sensor_host.protocol.sdf1 import HEADER_SIZE, MessageType
from sensor_host.transport import AcceptedGatewayClient


_HEADER = struct.Struct("<4sBBHHHIQHH")
_DEVICE_UUID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")


def _cli_frame(text: str, sequence: int) -> bytes:
    payload = text.encode()
    header = _HEADER.pack(
        b"SDF1", 1, int(MessageType.CLI_RESPONSE), 0, HEADER_SIZE,
        len(payload), sequence, 100, 1, 0,
    )
    content = header + payload
    return content + struct.pack("<I", zlib.crc32(content) & 0xFFFFFFFF)


class RecordingIdleTransport:
    def __init__(self) -> None:
        self.commands: list[bytes] = []

    def open(self, device_id: str) -> None:
        self.device_id = device_id

    def close(self) -> None:
        pass

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        return b""

    def write_control(self, command: bytes) -> None:
        self.commands.append(command)

    def write_raw(self, data: bytes) -> None:
        self.commands.append(data)


class OtaBenchTransport:
    """Wi-Fi-style transport: SDF1 CLI frames plus bare OTA replies and reset."""

    def __init__(
        self,
        device_uuid: uuid.UUID = _DEVICE_UUID,
        *,
        app_version: str = "1.0.0",
        staged_crc: int | None = None,
        reset_after_staged: bool = True,
    ) -> None:
        self._uuid = device_uuid
        self._out: deque = deque()
        self._lock = threading.Lock()
        self._seq = 0
        self.commands: list[bytes] = []
        self.raw_writes: list[bytes] = []
        self._ota_next = 0
        self._ota_image = bytearray()
        self._app_version = app_version
        self._staged_crc = staged_crc
        self._reset_after_staged = reset_after_staged
        self.closed = False

    def discover(self):
        return []

    def open(self, device_id: str) -> None:
        self.device_id = device_id

    def close(self) -> None:
        self.closed = True

    def write_control(self, command: bytes) -> None:
        self.commands.append(bytes(command))
        text = bytes(command).decode("ascii", "replace").strip().upper()
        if text == "AT+UUID?":
            self._push_cli(f"+UUID:{self._uuid},SOURCE=DERIVED\r\nOK\r\n")
        elif text == "AT+STATE?":
            self._push_cli(
                "+STATE:IDLE\r\n"
                "+SD:USED=0,CAPACITY=1000,PENDING_FRAMES=0,RETAINED_CHUNKS=0,"
                "RETAINED_FRAMES=0,OVERWRITTEN_CHUNKS=0,OVERWRITTEN_FRAMES=0,"
                "READY=1,FORMAT_REQUIRED=0\r\n"
                "+OTA:STATE=OFF,RECEIVED=0,TOTAL=0,ERROR=0\r\nOK\r\n"
            )
        elif text == "AT+LIVESTREAM?":
            self._push_cli("+LIVESTREAM:UART\r\nOK\r\n")
        else:
            self._push_cli("OK\r\n")

    def write_raw(self, data: bytes) -> None:
        self.raw_writes.append(bytes(data))
        if data.startswith(b"AT+OTA"):
            self._ota_next = 0
            self._ota_image = bytearray()
            self._push(b"+OTA:READY,PROTO=1,MAX=327680,CHUNK=512\r\nOK\r\n")
            return
        frame = decode_frame(data)
        if frame.frame_type is FrameType.BEGIN:
            self._push(b"+OTA:ACK,SEQ=0,NEXT=0\r\n")
        elif frame.frame_type is FrameType.DATA:
            if frame.offset == self._ota_next:
                self._ota_image.extend(frame.payload)
                self._ota_next += len(frame.payload)
            self._push(
                f"+OTA:ACK,SEQ={frame.sequence},NEXT={self._ota_next}\r\n".encode()
            )
        elif frame.frame_type is FrameType.COMMIT:
            crc = (
                self._staged_crc
                if self._staged_crc is not None
                else zlib.crc32(bytes(self._ota_image)) & 0xFFFFFFFF
            )
            self._push(
                f"+OTA:STAGED,VERSION={self._app_version},CRC={crc:08X}\r\nOK\r\n".encode()
            )
            if self._reset_after_staged:
                self._push(OSError("device reset after staging"))
        elif frame.frame_type is FrameType.CANCEL:
            self._push(
                f"+OTA:ACK,SEQ={frame.sequence},NEXT={self._ota_next}\r\n".encode()
            )

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        deadline = time.monotonic() + timeout_s
        while True:
            with self._lock:
                if self._out:
                    item = self._out.popleft()
                    if isinstance(item, BaseException):
                        raise item
                    return item if len(item) <= max_bytes else item[:max_bytes]
            if time.monotonic() >= deadline:
                return b""
            time.sleep(0.002)

    def _push(self, item) -> None:
        with self._lock:
            self._out.append(item)

    def _push_cli(self, text: str) -> None:
        self._seq += 1
        self._push(_cli_frame(text, self._seq))


def _sd_ready(controller: AppController, node_id: str) -> bool:
    session = controller._sessions.get(node_id)
    if session is None:
        return False
    state = session.store.snapshot(1.0, 2).firmware_control_state
    return state is not None and state.sd_ready is True


def _write_package(tmp_path, image_size: int = 1200, version: str = "1.0.0"):
    image = bytes((index * 3 + 1) & 0xFF for index in range(image_size))
    path = tmp_path / "app.ota"
    path.write_bytes(pack_ota(image=image, app_version=version))
    return path


def test_wifi_ota_full_lifecycle_stages_and_reconnects(qtbot, tmp_path) -> None:
    transport = OtaBenchTransport()
    controller = AppController(RecordingIdleTransport)
    states: list[tuple[str, str, str]] = []
    staged: list[tuple] = []
    errors: list[str] = []
    controller.ota_state.connect(lambda n, s, d: states.append((n, s, d)))
    controller.ota_staged.connect(lambda n, v, c, m: staged.append((n, v, c, m)))
    controller.error_raised.connect(errors.append)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    try:
        qtbot.waitUntil(
            lambda: controller._session_index.summary("wifi-1").device_uuid
            == _DEVICE_UUID,
            timeout=3000,
        )
        qtbot.waitUntil(lambda: _sd_ready(controller, "wifi-1"), timeout=3000)

        package_path = _write_package(tmp_path)
        controller.start_ota_for("wifi-1", str(package_path))

        qtbot.waitUntil(
            lambda: any(state[1] == "WAIT_RESTART" for state in states), timeout=8000
        )
        assert staged and staged[0][3] is True  # version/CRC matched the package

        # The expected post-STAGED reset drops the session but is not an error.
        qtbot.waitUntil(lambda: "wifi-1" not in controller._sessions, timeout=4000)
        assert not any("reset" in error for error in errors)
        assert controller.ota_active_node() == "wifi-1"

        # The device reboots and the ESP bridge reconnects as a new session.
        rebooted = OtaBenchTransport(reset_after_staged=False)
        controller.accept_gateway_client(
            AcceptedGatewayClient("wifi-2", "peer-2", rebooted)  # type: ignore[arg-type]
        )
        qtbot.waitUntil(
            lambda: any(state[1] == "RECONNECTED" for state in states), timeout=8000
        )
        assert controller.ota_active_node() is None
    finally:
        controller.disconnect_device()


def test_cdc_session_rejects_ota(qtbot, tmp_path) -> None:
    transport = OtaBenchTransport()
    controller = AppController(lambda: transport)
    states: list[tuple[str, str, str]] = []
    errors: list[str] = []
    controller.ota_state.connect(lambda n, s, d: states.append((n, s, d)))
    controller.error_raised.connect(errors.append)
    controller.connect_device("FAKE")
    try:
        qtbot.waitUntil(lambda: controller.selected_node_id == "cdc:FAKE", timeout=3000)
        package_path = _write_package(tmp_path)

        controller.start_ota_for("cdc:FAKE", str(package_path))

        assert any(state[1] == "SOURCE_REJECTED" for state in states)
        assert any("UART" in error for error in errors)
        assert transport.raw_writes == []
    finally:
        controller.disconnect_device()


def test_ota_blocks_concurrent_start_export_and_record(qtbot) -> None:
    transport = OtaBenchTransport()
    controller = AppController(RecordingIdleTransport)
    errors: list[str] = []
    controller.error_raised.connect(errors.append)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    session = controller._sessions["wifi-1"]
    try:
        session.ota_active = True  # simulate an in-flight upload

        controller.start_acquisition_for("wifi-1")
        controller.start_export_for("wifi-1")
        controller.set_recording(True)

        assert any("acquisition start is blocked" in error for error in errors)
        assert any("export is blocked" in error for error in errors)
        assert any("recording is blocked" in error for error in errors)
        assert controller._recording_active is False
    finally:
        session.ota_active = False
        controller.disconnect_device()


def test_staged_crc_mismatch_warns(qtbot, tmp_path) -> None:
    transport = OtaBenchTransport(staged_crc=0xDEADBEEF, reset_after_staged=False)
    controller = AppController(RecordingIdleTransport)
    staged: list[tuple] = []
    errors: list[str] = []
    controller.ota_staged.connect(lambda n, v, c, m: staged.append((n, v, c, m)))
    controller.error_raised.connect(errors.append)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    try:
        qtbot.waitUntil(
            lambda: controller._session_index.summary("wifi-1").device_uuid
            == _DEVICE_UUID,
            timeout=3000,
        )
        qtbot.waitUntil(lambda: _sd_ready(controller, "wifi-1"), timeout=3000)
        package_path = _write_package(tmp_path)

        controller.start_ota_for("wifi-1", str(package_path))

        qtbot.waitUntil(lambda: bool(staged), timeout=8000)
        assert staged[0][3] is False
        assert any("STAGED" in error for error in errors)
    finally:
        controller.disconnect_device()


def test_bad_package_is_rejected_before_upload(qtbot, tmp_path) -> None:
    transport = OtaBenchTransport()
    controller = AppController(RecordingIdleTransport)
    states: list[tuple[str, str, str]] = []
    errors: list[str] = []
    controller.ota_state.connect(lambda n, s, d: states.append((n, s, d)))
    controller.error_raised.connect(errors.append)
    controller.accept_gateway_client(
        AcceptedGatewayClient("wifi-1", "peer-1", transport)  # type: ignore[arg-type]
    )
    try:
        qtbot.waitUntil(lambda: _sd_ready(controller, "wifi-1"), timeout=3000)
        bad = tmp_path / "bad.ota"
        bad.write_bytes(pack_ota(image=bytes(600), app_version="1.0.0")[:-1])

        controller.start_ota_for("wifi-1", str(bad))

        assert any(state[1] == "PACKAGE_REJECTED" for state in states)
        assert transport.raw_writes == []
    finally:
        controller.disconnect_device()
