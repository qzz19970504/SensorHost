import time
from threading import Event, Thread

from sensor_host.acquisition import AcquisitionController, RealtimeSampleStore
from sensor_host.app import main
from sensor_host.protocol import MessageType, StreamParser
from sensor_host.transport import FakeTransport


def _read_cli(transport: FakeTransport) -> str:
    parser = StreamParser()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        frame = parser.feed(transport.read(65536, 0.05))
        if frame and frame[0].message_type is MessageType.CLI_RESPONSE:
            return frame[0].cli_text or ""
    raise AssertionError("fake transport did not return a CLI response")


def test_fake_transport_exposes_one_openable_device_and_state() -> None:
    transport = FakeTransport()

    devices = transport.discover()
    assert len(devices) == 1
    assert devices[0].device_id == FakeTransport.DEVICE_ID

    transport.open(FakeTransport.DEVICE_ID)
    transport.write_control(b"AT+STATE?")

    reply = _read_cli(transport)
    assert "+STATE:IDLE" in reply
    assert "+SD:USED=" in reply
    assert "+EXPORT:TARGET=NONE" in reply
    transport.close()


def test_fake_transport_frames_flow_through_real_acquisition_parser() -> None:
    transport = FakeTransport()
    transport.open(FakeTransport.DEVICE_ID)
    store = RealtimeSampleStore()
    controller = AcquisitionController(transport, store)

    observed_types: set[MessageType] = set()
    parser = StreamParser()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and observed_types != {
        MessageType.IIS3DWB_FIFO,
        MessageType.JY61PL_SAMPLE,
    }:
        observed_types.update(
            frame.message_type
            for frame in parser.feed(transport.read(65536, 0.05))
        )

    assert observed_types == {
        MessageType.IIS3DWB_FIFO,
        MessageType.JY61PL_SAMPLE,
    }
    transport.close()


def test_fake_transport_populates_the_real_acquisition_store() -> None:
    transport = FakeTransport()
    transport.open(FakeTransport.DEVICE_ID)
    store = RealtimeSampleStore()
    controller = AcquisitionController(transport, store)
    stop_event = Event()
    worker = Thread(
        target=controller.run,
        args=(stop_event,),
        daemon=True,
    )
    worker.start()

    deadline = time.monotonic() + 1.0
    snapshot = store.snapshot(1.0, 100)
    while time.monotonic() < deadline:
        snapshot = store.snapshot(1.0, 100)
        if snapshot.time_s.size and snapshot.orientation is not None:
            break
        time.sleep(0.01)

    stop_event.set()
    worker.join(timeout=1.0)
    assert not worker.is_alive()
    assert snapshot.time_s.size > 0
    assert snapshot.orientation is not None


def test_fake_transport_export_cancel_and_clear_follow_control_contract() -> None:
    transport = FakeTransport()
    transport.open(FakeTransport.DEVICE_ID)

    transport.write_control(b"AT+EXPORT=UART")
    assert "EXPORT_BEGIN:UART" in _read_cli(transport)

    parser = StreamParser()
    archive_seen = False
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not archive_seen:
        frames = parser.feed(transport.read(65536, 0.05))
        archive_seen = any(frame.archive_export for frame in frames)
    assert archive_seen

    transport.write_control(b"AT+STOP")
    assert _read_cli(transport).strip() == "OK"
    transport.write_control(b"AT+STATE?")
    state_reply = _read_cli(transport)
    assert "+STATE:IDLE" in state_reply
    assert "+EXPORT:TARGET=NONE" in state_reply

    transport.write_control(b"AT+SDCLEAR=CONFIRM")
    assert _read_cli(transport).strip() == "OK"
    transport.write_control(b"AT+STATE?")
    assert "+SD:USED=0" in _read_cli(transport)
    transport.close()


def test_fake_argument_selects_fake_interactive_factory(monkeypatch, qapp) -> None:
    captured: dict[str, object] = {}

    def fake_interactive(application, *, transport_factory, fake_mode):
        captured["application"] = application
        captured["transport_factory"] = transport_factory
        captured["fake_mode"] = fake_mode
        return 0

    monkeypatch.setattr("sensor_host.app._run_interactive", fake_interactive)

    assert main(["stm32-sensor-host", "--fake"]) == 0
    assert captured["application"] is qapp
    assert captured["transport_factory"] is FakeTransport
    assert captured["fake_mode"] is True
