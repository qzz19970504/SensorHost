import uuid

import pytest

from sensor_host.acquisition import (
    ConnectionState,
    DuplicateDeviceError,
    NodeSessionManager,
    SessionCapacityError,
    TransportKind,
)


def test_session_manager_enforces_sixteen_active_connections() -> None:
    manager = NodeSessionManager(maximum_sessions=16)
    for node_number in range(16):
        manager.add_session(
            f"wifi-{node_number}", TransportKind.WIFI, f"192.168.43.{node_number + 2}:5000"
        )

    with pytest.raises(SessionCapacityError):
        manager.add_session("wifi-17", TransportKind.WIFI, "192.168.43.99:5000")


def test_session_manager_binds_uuid_and_reuses_saved_alias_after_reconnect() -> None:
    device_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    manager = NodeSessionManager(
        maximum_sessions=16,
        aliases={str(device_uuid): "Pump House"},
    )
    manager.add_session("wifi-1", TransportKind.WIFI, "192.168.43.20:5000")
    manager.bind_identity("wifi-1", device_uuid)
    manager.mark_reconnecting("wifi-1", "hotspot lost")

    manager.add_session("wifi-2", TransportKind.WIFI, "192.168.43.21:5001")
    summary = manager.bind_identity("wifi-2", device_uuid)

    assert summary.alias == "Pump House"
    assert summary.connection_state is ConnectionState.CONNECTED
    assert [node.node_id for node in manager.summaries()] == ["wifi-2"]


def test_session_manager_rejects_duplicate_online_uuid() -> None:
    device_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    manager = NodeSessionManager(maximum_sessions=16)
    manager.add_session("wifi-1", TransportKind.WIFI, "peer-1")
    manager.add_session("wifi-2", TransportKind.WIFI, "peer-2")
    manager.bind_identity("wifi-1", device_uuid)

    with pytest.raises(DuplicateDeviceError, match="already online"):
        manager.bind_identity("wifi-2", device_uuid)


def test_session_manager_updates_alias_and_recording_state() -> None:
    device_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    manager = NodeSessionManager(maximum_sessions=16)
    manager.add_session("wifi-1", TransportKind.WIFI, "peer")
    manager.bind_identity("wifi-1", device_uuid)

    manager.set_alias("wifi-1", "North Motor")
    manager.set_recording("wifi-1", True)

    summary = manager.summary("wifi-1")
    assert summary.alias == "North Motor"
    assert summary.is_recording is True
    assert manager.aliases[str(device_uuid)] == "North Motor"
