from __future__ import annotations

import socket

import pytest

from sensor_host.transport import (
    AcceptedSocketTransport,
    GatewayListener,
    TransportError,
    UdpWakeService,
    WifiServerConfig,
)


def test_accepted_socket_transport_preserves_stream_and_control_bytes() -> None:
    server_socket, client_socket = socket.socketpair()
    transport = AcceptedSocketTransport(server_socket, "192.168.43.21:50000")
    try:
        client_socket.sendall(b"SDF1-partial")
        assert transport.read(64, 0.2) == b"SDF1-partial"

        transport.write_control(b"AT+STATE?\n")
        assert client_socket.recv(64) == b"AT+STATE?\r\n"
    finally:
        transport.close()
        client_socket.close()


def test_accepted_socket_transport_reports_orderly_disconnect() -> None:
    server_socket, client_socket = socket.socketpair()
    transport = AcceptedSocketTransport(server_socket, "peer")
    client_socket.close()

    with pytest.raises(TransportError, match="disconnected"):
        transport.read(64, 0.2)

    transport.close()


def test_gateway_listener_accepts_up_to_configured_capacity() -> None:
    listener = GatewayListener(maximum_clients=2)
    listener.start("127.0.0.1", 0)
    clients: list[socket.socket] = []
    accepted = []
    try:
        for _client_index in range(3):
            client = socket.create_connection(("127.0.0.1", listener.bound_port))
            clients.append(client)
            accepted.append(listener.accept(0.5))

        assert accepted[0] is not None
        assert accepted[1] is not None
        assert accepted[2] is None
        assert listener.rejected_clients == 1
    finally:
        for accepted_client in accepted:
            if accepted_client is not None:
                accepted_client.transport.close()
                listener.release(accepted_client.connection_id)
        for client in clients:
            client.close()
        listener.close()


class RecordingDatagramSocket:
    def __init__(self) -> None:
        self.options: list[tuple[int, int, int]] = []
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def setsockopt(self, level: int, option: int, value: int) -> None:
        self.options.append((level, option, value))

    def sendto(self, payload: bytes, destination: tuple[str, int]) -> int:
        self.sent.append((payload, destination))
        return len(payload)

    def close(self) -> None:
        pass


def test_udp_wake_sends_broadcast_and_unique_unicast_targets() -> None:
    datagram_socket = RecordingDatagramSocket()
    service = UdpWakeService(
        local_ipv4="192.168.43.100",
        netmask="255.255.255.0",
        udp_port=12345,
        unicast_targets=("192.168.43.20", "192.168.43.20", "192.168.43.21"),
        socket_factory=lambda: datagram_socket,
    )

    service.send_once()

    assert datagram_socket.sent == [
        (b"TCPCONNECT", ("192.168.43.255", 12345)),
        (b"TCPCONNECT", ("192.168.43.20", 12345)),
        (b"TCPCONNECT", ("192.168.43.21", 12345)),
    ]


def test_wifi_server_config_requires_esp_target_to_match_selected_pc_ip() -> None:
    with pytest.raises(ValueError, match="does not match"):
        WifiServerConfig(
            local_ipv4="192.168.43.100",
            netmask="255.255.255.0",
            expected_pc_ipv4="192.168.43.101",
        )


def test_wifi_server_config_rejects_loopback_interface() -> None:
    with pytest.raises(ValueError, match="loopback"):
        WifiServerConfig(
            local_ipv4="127.0.0.1",
            netmask="255.0.0.0",
            expected_pc_ipv4="127.0.0.1",
        )
