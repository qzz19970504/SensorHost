"""Public acquisition transport interfaces."""

from .base import DeviceDescriptor, Transport, TransportError
from .cdc_serial import CdcSerialTransport
from .gateway import (
    DEFAULT_MAXIMUM_CLIENTS,
    DEFAULT_TCP_PORT,
    DEFAULT_UDP_PORT,
    AcceptedGatewayClient,
    AcceptedSocketTransport,
    GatewayListener,
    UdpWakeService,
    WifiServerConfig,
)

__all__ = [
    "AcceptedGatewayClient",
    "AcceptedSocketTransport",
    "CdcSerialTransport",
    "DEFAULT_MAXIMUM_CLIENTS",
    "DEFAULT_TCP_PORT",
    "DEFAULT_UDP_PORT",
    "DeviceDescriptor",
    "GatewayListener",
    "Transport",
    "TransportError",
    "UdpWakeService",
    "WifiServerConfig",
]
