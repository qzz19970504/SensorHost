import uuid

import pytest

from sensor_host.protocol import ControlStateParseError, FirmwareControlState


FULL_STATE_REPLY = (
    "+STATE:ACQUIRE\r\n"
    "+BAUD:115200\r\n"
    "+UUID:550e8400-e29b-41d4-a716-446655440000,SOURCE=DERIVED\r\n"
    "+SD:USED=10,CAPACITY=100,PENDING_FRAMES=2,RETAINED_CHUNKS=1,"
    "RETAINED_FRAMES=8,OVERWRITTEN_CHUNKS=3,OVERWRITTEN_FRAMES=20,"
    "READY=1,FORMAT_REQUIRED=0\r\n"
    "+EXPORT:TARGET=UART,CHUNK=4,FRAME=5\r\n"
    "+LIVE:TARGET=UART,DROPS_IIS=6,DROPS_JY=7,LAST_ROUTED_SEQUENCE=8,"
    "LAST_COMPLETED_SEQUENCE=9\r\n"
    "+DIAG:POOL_FAIL=1,INGRESS_DROP=2,NOSTORE_DROP=3,POOL_MIN=4,"
    "INGRESS_PEAK=5,SD_STALL_MS=6,CDC_LIVE=7,CDC_CTRL=8,CDC_EXPORT=9\r\n"
    "+STOP_REASON:COMMAND\r\n"
    "OK\r\n"
)


def test_control_state_parses_current_firmware_state_reply() -> None:
    state = FirmwareControlState().updated_from_cli(FULL_STATE_REPLY)

    assert state.acquisition_state == "ACQUIRE"
    assert state.uart_baud == 115200
    assert state.device_uuid == uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    assert state.uuid_source == "DERIVED"
    assert state.sd_ready is True
    assert state.sd_format_required is False
    assert state.sd_used == 10
    assert state.export_target == "UART"
    assert state.export_chunk == 4
    assert state.livestream_target == "UART"
    assert state.live_drops_iis == 6
    assert state.diag_cdc_export == 9
    assert state.stop_reason == "COMMAND"


def test_control_state_merges_partial_query_replies() -> None:
    initial = FirmwareControlState().updated_from_cli("+STATE:IDLE\r\n")

    updated = initial.updated_from_cli("+LIVESTREAM:CDC\r\nOK\r\n")

    assert updated.acquisition_state == "IDLE"
    assert updated.livestream_target == "CDC"


@pytest.mark.parametrize(
    "reply",
    [
        "+STATE:IDLE\r\n+STATE:ACQUIRE\r\n",
        "+LIVE:TARGET=UART,TARGET=CDC\r\n",
        f"+SD:USED={1 << 64}\r\n",
    ],
)
def test_control_state_rejects_ambiguous_or_oversized_fields(reply: str) -> None:
    with pytest.raises(ControlStateParseError):
        FirmwareControlState().updated_from_cli(reply)


@pytest.mark.parametrize(
    ("reply", "phase"),
    [
        ("EXPORT_BEGIN:UART\r\nOK\r\n", "IN_PROGRESS"),
        ("EXPORT_EMPTY\r\n", "EMPTY"),
        ("EXPORT_END:CHUNKS=2,FRAMES=30\r\n", "COMPLETE"),
        ("EXPORT_ABORTED\r\n", "ABORTED"),
    ],
)
def test_control_state_tracks_export_lifecycle(reply: str, phase: str) -> None:
    state = FirmwareControlState().updated_from_cli(reply)

    assert state.export_phase == phase
    assert state.export_revision == 1


def test_control_state_increments_export_event_revision() -> None:
    first = FirmwareControlState().updated_from_cli("EXPORT_END:CHUNKS=1,FRAMES=2\r\n")
    second = first.updated_from_cli("EXPORT_END:CHUNKS=3,FRAMES=4\r\n")

    assert second.export_revision == 2
