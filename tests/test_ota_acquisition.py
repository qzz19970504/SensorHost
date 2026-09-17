"""Integration tests for the AcquisitionController OTA bridge and demux path."""

from __future__ import annotations

import zlib
from threading import Event, Thread

from sensor_host.acquisition import AcquisitionController, RealtimeSampleStore
from sensor_host.ota.package import pack_ota
from sensor_host.ota.uploader import OtaUploader
from sensor_host.protocol import MessageType
from sensor_host.transport import FakeTransport


class ControllerOtaTransport:
    """Adapt the AcquisitionController OTA bridge to the uploader contract."""

    def __init__(self, controller: AcquisitionController) -> None:
        self._controller = controller

    def send(self, data: bytes) -> None:
        self._controller.send_ota_frame(data)

    def readline(self, timeout: float) -> bytes | None:
        return self._controller.next_ota_reply(timeout)


def _run_controller(controller: AcquisitionController, stop_event: Event) -> Thread:
    worker = Thread(target=controller.run, args=(stop_event,), daemon=True)
    worker.start()
    return worker


def test_full_upload_flows_through_controller_bridge() -> None:
    transport = FakeTransport()
    transport.open(FakeTransport.DEVICE_ID)
    store = RealtimeSampleStore()
    controller = AcquisitionController(transport, store)
    stop_event = Event()
    worker = _run_controller(controller, stop_event)

    image = bytes((index * 11 + 1) & 0xFF for index in range(1500))
    package = pack_ota(image=image, app_version="1.0.0")
    expected_crc = zlib.crc32(image) & 0xFFFFFFFF

    try:
        controller.start_ota()
        assert controller.ota_active is True

        result = OtaUploader(ack_timeout=2.0, commit_timeout=5.0).upload(
            package=package,
            transport=ControllerOtaTransport(controller),
        )

        assert result["staged_version"] == "1.0.0"
        assert result["staged_crc"] == expected_crc
        assert result["image_size"] == len(image)
        # The device saw the ASCII begin command plus BEGIN/DATA/COMMIT frames.
        assert transport.raw_writes[0].startswith(b"AT+OTA=BEGIN")
        assert len(transport.raw_writes) >= 1 + 1 + 3 + 1
        # Bare +OTA/OK lines were demuxed away and never reached the parser.
        assert controller._parser.stats.bytes_discarded == 0
    finally:
        controller.end_ota()
        stop_event.set()
        worker.join(timeout=2.0)
        transport.close()

    assert not worker.is_alive()


def test_live_frames_resume_after_ota_session_ends() -> None:
    transport = FakeTransport()
    transport.open(FakeTransport.DEVICE_ID)
    store = RealtimeSampleStore()
    controller = AcquisitionController(transport, store)
    stop_event = Event()
    worker = _run_controller(controller, stop_event)

    image = bytes((index * 5 + 2) & 0xFF for index in range(600))
    package = pack_ota(image=image, app_version="1.0.0")

    try:
        controller.start_ota()
        OtaUploader(ack_timeout=2.0, commit_timeout=5.0).upload(
            package=package, transport=ControllerOtaTransport(controller)
        )
        controller.end_ota()
        assert controller.ota_active is False

        # After OTA the fake resumes live SDF1 frames; the parser must decode
        # them again with no residual demux corruption.
        deadline_types: set[MessageType] = set()
        import time

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not deadline_types:
            snapshot = store.snapshot(1.0, 100)
            if snapshot.time_s.size:
                deadline_types.add(MessageType.IIS3DWB_FIFO)
            time.sleep(0.01)
        assert controller._parser.stats.bytes_discarded == 0
    finally:
        stop_event.set()
        worker.join(timeout=2.0)
        transport.close()


def test_send_and_reply_bridge_is_thread_safe_without_ota() -> None:
    # With OTA disarmed the outbound queue is never written and normal parsing
    # is unaffected; a stray next_ota_reply simply times out.
    transport = FakeTransport()
    transport.open(FakeTransport.DEVICE_ID)
    controller = AcquisitionController(transport, RealtimeSampleStore())

    assert controller.ota_active is False
    assert controller.next_ota_reply(0.01) is None
    assert transport.raw_writes == []
    transport.close()
