"""Public acquisition transport interfaces."""

from .base import DeviceDescriptor, Transport, TransportError
from .cdc_serial import CdcSerialTransport

__all__ = [
    "CdcSerialTransport",
    "DeviceDescriptor",
    "Transport",
    "TransportError",
]
