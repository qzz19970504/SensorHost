"""TCP server-side stream transport and UDP wake support for ESP gateways."""

from __future__ import annotations

import ipaddress
import socket
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from sensor_host.transport.base import DeviceDescriptor, TransportError


DEFAULT_TCP_PORT = 54_321
DEFAULT_UDP_PORT = 12_345
DEFAULT_MAXIMUM_CLIENTS = 16
DEFAULT_WAKE_INTERVAL_SECONDS = 2.0
_MAXIMUM_CONTROL_BYTES = 94
_MAXIMUM_ASCII_BYTE = 0x7F
_WAKE_PAYLOAD = b"TCPCONNECT"


@dataclass(frozen=True)
class WifiServerConfig:
    """Validate the host endpoint that preconfigured ESP gateways connect to."""

    local_ipv4: str
    netmask: str
    expected_pc_ipv4: str
    tcp_port: int = DEFAULT_TCP_PORT
    udp_port: int = DEFAULT_UDP_PORT
    unicast_targets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        interface = ipaddress.IPv4Interface(f"{self.local_ipv4}/{self.netmask}")
        expected = ipaddress.IPv4Address(self.expected_pc_ipv4)
        if interface.ip.is_loopback:
            raise ValueError("Wi-Fi interface must not be loopback")
        if interface.ip != expected:
            raise ValueError(
                "ESP configured PC IPv4 does not match the selected interface"
            )
        if not 1 <= self.tcp_port <= 65_535:
            raise ValueError("TCP port must be in 1..65535")
        if not 1 <= self.udp_port <= 65_535:
            raise ValueError("UDP port must be in 1..65535")
        for target in self.unicast_targets:
            ipaddress.IPv4Address(target)


class _DatagramSocket(Protocol):
    def setsockopt(self, level: int, option: int, value: int) -> None: ...
    def sendto(self, payload: bytes, destination: tuple[str, int]) -> int: ...
    def close(self) -> None: ...


class AcceptedSocketTransport:
    """Expose one accepted TCP connection as a raw SDF1 transport."""

    def __init__(self, stream_socket: socket.socket, peer: str) -> None:
        self._socket: socket.socket | None = stream_socket
        self.peer = peer

    def discover(self) -> list[DeviceDescriptor]:
        return []

    def open(self, device_id: str) -> None:
        if self._socket is None:
            raise TransportError(f"gateway connection {device_id} is closed")

    def close(self) -> None:
        stream_socket = self._socket
        self._socket = None
        if stream_socket is None:
            return
        try:
            stream_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        stream_socket.close()

    def read(self, max_bytes: int, timeout_s: float) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if timeout_s < 0.0:
            raise ValueError("timeout_s must not be negative")
        stream_socket = self._require_socket()
        stream_socket.settimeout(timeout_s)
        try:
            payload = stream_socket.recv(max_bytes)
        except socket.timeout:
            return b""
        except OSError as error:
            raise TransportError(f"cannot read gateway {self.peer}: {error}") from error
        if not payload:
            raise TransportError(f"gateway {self.peer} disconnected")
        return payload

    def write_control(self, command: bytes) -> None:
        content = bytes(command).rstrip(b"\r\n")
        if not content or len(content) > _MAXIMUM_CONTROL_BYTES:
            raise ValueError("control command must contain 1..94 bytes")
        if b"\x00" in content or any(value > _MAXIMUM_ASCII_BYTE for value in content):
            raise ValueError("control command must contain ASCII without NUL")
        try:
            self._require_socket().sendall(content + b"\r\n")
        except OSError as error:
            raise TransportError(f"cannot write gateway {self.peer}: {error}") from error

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise TransportError(f"gateway {self.peer} is closed")
        return self._socket


@dataclass(frozen=True)
class AcceptedGatewayClient:
    """Describe one accepted gateway connection and its stream transport."""

    connection_id: str
    peer: str
    transport: AcceptedSocketTransport


class GatewayListener:
    """Accept a bounded number of ESP TCP clients on one local endpoint."""

    def __init__(self, maximum_clients: int = DEFAULT_MAXIMUM_CLIENTS) -> None:
        if maximum_clients <= 0:
            raise ValueError("maximum_clients must be positive")
        self._maximum_clients = maximum_clients
        self._listener: socket.socket | None = None
        self._active_connections: set[str] = set()
        self._next_connection_number = 1
        self._lock = threading.Lock()
        self.bound_port = 0
        self.rejected_clients = 0

    def start(self, local_ipv4: str, tcp_port: int) -> None:
        if self._listener is not None:
            raise TransportError("gateway listener is already running")
        ipaddress.IPv4Address(local_ipv4)
        if not 0 <= tcp_port <= 65_535:
            raise ValueError("TCP port must be in 0..65535")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((local_ipv4, tcp_port))
            listener.listen(self._maximum_clients)
        except OSError as error:
            listener.close()
            raise TransportError(
                f"cannot listen on {local_ipv4}:{tcp_port}: {error}"
            ) from error
        self._listener = listener
        self.bound_port = int(listener.getsockname()[1])

    def accept(self, timeout_s: float) -> AcceptedGatewayClient | None:
        listener = self._listener
        if listener is None:
            raise TransportError("gateway listener is not running")
        listener.settimeout(timeout_s)
        try:
            stream_socket, peer_address = listener.accept()
        except socket.timeout:
            return None
        except OSError as error:
            if self._listener is None:
                return None
            raise TransportError(f"gateway listener failed: {error}") from error
        peer = f"{peer_address[0]}:{peer_address[1]}"
        with self._lock:
            if len(self._active_connections) >= self._maximum_clients:
                self.rejected_clients += 1
                stream_socket.close()
                return None
            connection_id = f"wifi-{self._next_connection_number}"
            self._next_connection_number += 1
            self._active_connections.add(connection_id)
        return AcceptedGatewayClient(
            connection_id=connection_id,
            peer=peer,
            transport=AcceptedSocketTransport(stream_socket, peer),
        )

    def release(self, connection_id: str) -> None:
        with self._lock:
            self._active_connections.discard(connection_id)

    def close(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.close()


class UdpWakeService:
    """Periodically wake ESP gateways through their existing UDP command."""

    def __init__(
        self,
        local_ipv4: str,
        netmask: str,
        udp_port: int = DEFAULT_UDP_PORT,
        unicast_targets: Iterable[str] = (),
        interval_s: float = DEFAULT_WAKE_INTERVAL_SECONDS,
        socket_factory: Callable[[], _DatagramSocket] | None = None,
    ) -> None:
        interface = ipaddress.IPv4Interface(f"{local_ipv4}/{netmask}")
        if interface.ip.is_loopback:
            raise ValueError("wake interface must not be loopback")
        if not 1 <= udp_port <= 65_535:
            raise ValueError("UDP port must be in 1..65535")
        if interval_s <= 0.0:
            raise ValueError("wake interval must be positive")
        unique_targets = tuple(
            dict.fromkeys(
                str(ipaddress.IPv4Address(target)) for target in unicast_targets
            )
        )
        self._targets = (str(interface.network.broadcast_address),) + unique_targets
        self._udp_port = udp_port
        self._interval_s = interval_s
        self._socket_factory = socket_factory or self._create_socket
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def send_once(self) -> None:
        datagram_socket = self._socket_factory()
        try:
            datagram_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for target in self._targets:
                sent = datagram_socket.sendto(_WAKE_PAYLOAD, (target, self._udp_port))
                if sent != len(_WAKE_PAYLOAD):
                    raise TransportError(f"short UDP wake write to {target}")
        except OSError as error:
            raise TransportError(f"cannot send UDP gateway wake: {error}") from error
        finally:
            datagram_socket.close()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="gateway-udp-wake",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._interval_s + 1.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.send_once()
                self.last_error = None
            except TransportError as error:
                self.last_error = str(error)
            self._stop_event.wait(self._interval_s)

    @staticmethod
    def _create_socket() -> socket.socket:
        return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
