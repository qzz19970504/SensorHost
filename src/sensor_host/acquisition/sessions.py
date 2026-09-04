"""Logical multi-node session inventory independent of Qt and transports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import Enum
from threading import Lock

from sensor_host.acquisition.models import ConnectionState


class TransportKind(str, Enum):
    """Identify the physical path used by one host node session."""

    CDC = "cdc"
    WIFI = "wifi"


class SessionCapacityError(RuntimeError):
    """Report that the configured active-node limit has been reached."""


class DuplicateDeviceError(RuntimeError):
    """Report the same UUID appearing on two active physical connections."""


@dataclass(frozen=True)
class NodeSummary:
    """Describe one node for presentation without exposing session internals."""

    node_id: str
    transport_kind: TransportKind
    peer: str
    connection_state: ConnectionState
    device_uuid: uuid.UUID | None = None
    alias: str = ""
    is_recording: bool = False
    alert: str | None = None


class NodeSessionManager:
    """Track bounded logical identities across physical reconnects."""

    def __init__(
        self,
        maximum_sessions: int,
        aliases: dict[str, str] | None = None,
    ) -> None:
        if maximum_sessions <= 0:
            raise ValueError("maximum_sessions must be positive")
        self._maximum_sessions = maximum_sessions
        self._aliases = dict(aliases or {})
        self._nodes: dict[str, NodeSummary] = {}
        self._lock = Lock()

    @property
    def aliases(self) -> dict[str, str]:
        """Return a copy of UUID aliases suitable for persistent storage."""
        with self._lock:
            return dict(self._aliases)

    def add_session(
        self,
        node_id: str,
        transport_kind: TransportKind,
        peer: str,
    ) -> NodeSummary:
        """Register one newly connected physical session."""
        if not node_id or not peer:
            raise ValueError("node_id and peer must not be empty")
        with self._lock:
            active_count = sum(
                node.connection_state is ConnectionState.CONNECTED
                for node in self._nodes.values()
            )
            if active_count >= self._maximum_sessions:
                raise SessionCapacityError("maximum active node count reached")
            if node_id in self._nodes:
                raise ValueError(f"node session {node_id} already exists")
            summary = NodeSummary(
                node_id=node_id,
                transport_kind=transport_kind,
                peer=peer,
                connection_state=ConnectionState.CONNECTED,
                alias=peer,
            )
            self._nodes[node_id] = summary
            return summary

    def bind_identity(self, node_id: str, device_uuid: uuid.UUID) -> NodeSummary:
        """Bind a UUID, rejecting online duplicates and replacing stale entries."""
        with self._lock:
            current = self._require_node(node_id)
            stale_node_ids: list[str] = []
            for existing_id, existing in self._nodes.items():
                if existing_id == node_id or existing.device_uuid != device_uuid:
                    continue
                if existing.connection_state is ConnectionState.CONNECTED:
                    raise DuplicateDeviceError(f"device {device_uuid} is already online")
                stale_node_ids.append(existing_id)
            for stale_node_id in stale_node_ids:
                del self._nodes[stale_node_id]
            alias = self._aliases.get(str(device_uuid), f"Node {str(device_uuid)[:8]}")
            updated = replace(current, device_uuid=device_uuid, alias=alias)
            self._nodes[node_id] = updated
            return updated

    def mark_reconnecting(self, node_id: str, reason: str | None = None) -> None:
        """Retain node identity while marking its physical session unavailable."""
        with self._lock:
            current = self._require_node(node_id)
            self._nodes[node_id] = replace(
                current,
                connection_state=ConnectionState.RECONNECTING,
                is_recording=False,
                alert=reason,
            )

    def mark_offline(self, node_id: str, reason: str | None = None) -> None:
        """Mark a node unavailable when no automatic reconnect is active."""
        with self._lock:
            current = self._require_node(node_id)
            self._nodes[node_id] = replace(
                current,
                connection_state=ConnectionState.OFFLINE,
                is_recording=False,
                alert=reason,
            )

    def set_alias(self, node_id: str, alias: str) -> NodeSummary:
        """Update one display alias and remember it for the node UUID."""
        normalized = alias.strip()
        if not normalized or len(normalized) > 64:
            raise ValueError("alias must contain 1..64 characters")
        with self._lock:
            current = self._require_node(node_id)
            updated = replace(current, alias=normalized)
            self._nodes[node_id] = updated
            if current.device_uuid is not None:
                self._aliases[str(current.device_uuid)] = normalized
            return updated

    def set_recording(self, node_id: str, is_recording: bool) -> None:
        """Update one node recording indicator."""
        with self._lock:
            current = self._require_node(node_id)
            self._nodes[node_id] = replace(current, is_recording=is_recording)

    def remove(self, node_id: str) -> None:
        """Remove one node from the current inventory."""
        with self._lock:
            self._nodes.pop(node_id, None)

    def summary(self, node_id: str) -> NodeSummary:
        """Return one immutable summary or raise for an unknown node."""
        with self._lock:
            return self._require_node(node_id)

    def summaries(self) -> list[NodeSummary]:
        """Return all current node summaries in stable identifier order."""
        with self._lock:
            return [self._nodes[node_id] for node_id in sorted(self._nodes)]

    def _require_node(self, node_id: str) -> NodeSummary:
        try:
            return self._nodes[node_id]
        except KeyError as error:
            raise KeyError(f"unknown node: {node_id}") from error
