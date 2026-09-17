"""Structured decoding for line-oriented firmware control responses."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace


_MAXIMUM_UNSIGNED_VALUE = (1 << 64) - 1
_KEY_VALUE_PATTERN = re.compile(r"([A-Z_]+)=([^,]+)")


class ControlStateParseError(ValueError):
    """Report an ambiguous or invalid structured firmware response."""


@dataclass(frozen=True)
class FirmwareControlState:
    """Hold the latest structured values observed in CLI response frames."""

    acquisition_state: str | None = None
    uart_baud: int | None = None
    device_uuid: uuid.UUID | None = None
    uuid_source: str | None = None
    sd_used: int | None = None
    sd_capacity: int | None = None
    sd_pending_frames: int | None = None
    sd_retained_chunks: int | None = None
    sd_retained_frames: int | None = None
    sd_overwritten_chunks: int | None = None
    sd_overwritten_frames: int | None = None
    sd_ready: bool | None = None
    sd_format_required: bool | None = None
    export_target: str | None = None
    export_chunk: int | None = None
    export_frame: int | None = None
    export_phase: str | None = None
    export_revision: int = 0
    export_chunks: int | None = None
    export_frames: int | None = None
    livestream_target: str | None = None
    live_drops_iis: int | None = None
    live_drops_jy: int | None = None
    live_last_routed_sequence: int | None = None
    live_last_completed_sequence: int | None = None
    diag_pool_fail: int | None = None
    diag_ingress_drop: int | None = None
    diag_nostore_drop: int | None = None
    diag_pool_min: int | None = None
    diag_ingress_peak: int | None = None
    diag_sd_stall_ms: int | None = None
    diag_cdc_live: int | None = None
    diag_cdc_ctrl: int | None = None
    diag_cdc_export: int | None = None
    stop_reason: str | None = None
    ota_state: str | None = None
    ota_received: int | None = None
    ota_total: int | None = None
    ota_error: int | None = None

    def updated_from_cli(self, response: str) -> "FirmwareControlState":
        """Return a copy updated with recognized fields from one CLI frame."""
        updates: dict[str, object] = {}
        seen_sections: set[str] = set()
        for raw_line in response.splitlines():
            line = raw_line.strip()
            if not line or line in {"OK", "ERROR"}:
                continue
            section = _section_name(line)
            if section is not None:
                if section in seen_sections:
                    raise ControlStateParseError(f"duplicate control section: {section}")
                seen_sections.add(section)
            _parse_line_into(line, updates)
        if any(line.strip().startswith("EXPORT_") for line in response.splitlines()):
            updates["export_revision"] = self.export_revision + 1
        return replace(self, **updates)


def _section_name(line: str) -> str | None:
    if line.startswith("+") and ":" in line:
        return line.split(":", 1)[0]
    if line.startswith("EXPORT_"):
        return "EXPORT_EVENT"
    return None


def _unsigned(value: str, field_name: str) -> int:
    if not value.isdecimal():
        raise ControlStateParseError(f"{field_name} must be unsigned decimal")
    parsed = int(value)
    if parsed > _MAXIMUM_UNSIGNED_VALUE:
        raise ControlStateParseError(f"{field_name} exceeds uint64")
    return parsed


def _boolean(value: str, field_name: str) -> bool:
    if value not in {"0", "1"}:
        raise ControlStateParseError(f"{field_name} must be 0 or 1")
    return value == "1"


def _key_values(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in _KEY_VALUE_PATTERN.finditer(content):
        key, value = match.groups()
        if key in values:
            raise ControlStateParseError(f"duplicate control field: {key}")
        values[key] = value
    return values


def _parse_line_into(line: str, updates: dict[str, object]) -> None:
    if line.startswith("+STATE:"):
        updates["acquisition_state"] = line.removeprefix("+STATE:")
        return
    if line.startswith("+BAUD:"):
        updates["uart_baud"] = _unsigned(line.removeprefix("+BAUD:"), "BAUD")
        return
    if line.startswith("+UUID:"):
        _parse_uuid(line.removeprefix("+UUID:"), updates)
        return
    if line.startswith("+SD:"):
        _parse_sd(_key_values(line.removeprefix("+SD:")), updates)
        return
    if line.startswith("+EXPORT:"):
        _parse_export_status(_key_values(line.removeprefix("+EXPORT:")), updates)
        return
    if line.startswith("+LIVE:"):
        _parse_live(line.removeprefix("+LIVE:"), updates)
        return
    if line.startswith("+LIVESTREAM:"):
        updates["livestream_target"] = line.removeprefix("+LIVESTREAM:")
        return
    if line.startswith("+DIAG:"):
        _parse_diag(_key_values(line.removeprefix("+DIAG:")), updates)
        return
    if line.startswith("+STOP_REASON:"):
        updates["stop_reason"] = line.removeprefix("+STOP_REASON:")
        return
    if line.startswith("+OTA:"):
        _parse_ota(_key_values(line.removeprefix("+OTA:")), updates)
        return
    _parse_export_event(line, updates)


def _parse_uuid(content: str, updates: dict[str, object]) -> None:
    parts = content.split(",")
    try:
        updates["device_uuid"] = uuid.UUID(parts[0])
    except ValueError as error:
        raise ControlStateParseError("invalid UUID response") from error
    if len(parts) > 1:
        values = _key_values(",".join(parts[1:]))
        if "SOURCE" in values:
            updates["uuid_source"] = values["SOURCE"]


def _parse_sd(values: dict[str, str], updates: dict[str, object]) -> None:
    integer_fields = {
        "USED": "sd_used",
        "CAPACITY": "sd_capacity",
        "PENDING_FRAMES": "sd_pending_frames",
        "RETAINED_CHUNKS": "sd_retained_chunks",
        "RETAINED_FRAMES": "sd_retained_frames",
        "OVERWRITTEN_CHUNKS": "sd_overwritten_chunks",
        "OVERWRITTEN_FRAMES": "sd_overwritten_frames",
    }
    for wire_name, field_name in integer_fields.items():
        if wire_name in values:
            updates[field_name] = _unsigned(values[wire_name], wire_name)
    if "READY" in values:
        updates["sd_ready"] = _boolean(values["READY"], "READY")
    if "FORMAT_REQUIRED" in values:
        updates["sd_format_required"] = _boolean(
            values["FORMAT_REQUIRED"], "FORMAT_REQUIRED"
        )


def _parse_export_status(values: dict[str, str], updates: dict[str, object]) -> None:
    if "TARGET" in values:
        updates["export_target"] = values["TARGET"]
    if "CHUNK" in values:
        updates["export_chunk"] = _unsigned(values["CHUNK"], "CHUNK")
    if "FRAME" in values:
        updates["export_frame"] = _unsigned(values["FRAME"], "FRAME")


def _parse_live(content: str, updates: dict[str, object]) -> None:
    values = _key_values(content)
    if "TARGET" in values:
        updates["livestream_target"] = values["TARGET"]
    integer_fields = {
        "DROPS_IIS": "live_drops_iis",
        "DROPS_JY": "live_drops_jy",
        "LAST_ROUTED_SEQUENCE": "live_last_routed_sequence",
        "LAST_COMPLETED_SEQUENCE": "live_last_completed_sequence",
    }
    for wire_name, field_name in integer_fields.items():
        if wire_name in values:
            updates[field_name] = _unsigned(values[wire_name], wire_name)


def _parse_diag(values: dict[str, str], updates: dict[str, object]) -> None:
    integer_fields = {
        "POOL_FAIL": "diag_pool_fail",
        "INGRESS_DROP": "diag_ingress_drop",
        "NOSTORE_DROP": "diag_nostore_drop",
        "POOL_MIN": "diag_pool_min",
        "INGRESS_PEAK": "diag_ingress_peak",
        "SD_STALL_MS": "diag_sd_stall_ms",
        "CDC_LIVE": "diag_cdc_live",
        "CDC_CTRL": "diag_cdc_ctrl",
        "CDC_EXPORT": "diag_cdc_export",
    }
    for wire_name, field_name in integer_fields.items():
        if wire_name in values:
            updates[field_name] = _unsigned(values[wire_name], wire_name)


def _parse_ota(values: dict[str, str], updates: dict[str, object]) -> None:
    # Only the ``+OTA:STATE=...,RECEIVED=...,TOTAL=...,ERROR=...`` form appears
    # inside an AT+STATE? CLI frame; the bare ACK/NACK/STAGED session replies
    # travel as raw stream lines and are demultiplexed before reaching here.
    if "STATE" in values:
        updates["ota_state"] = values["STATE"]
    integer_fields = {
        "RECEIVED": "ota_received",
        "TOTAL": "ota_total",
        "ERROR": "ota_error",
    }
    for wire_name, field_name in integer_fields.items():
        if wire_name in values:
            updates[field_name] = _unsigned(values[wire_name], wire_name)


def _parse_export_event(line: str, updates: dict[str, object]) -> None:
    if line.startswith("EXPORT_BEGIN:"):
        updates["export_phase"] = "IN_PROGRESS"
        updates["export_target"] = line.removeprefix("EXPORT_BEGIN:")
        return
    if line == "EXPORT_EMPTY":
        updates["export_phase"] = "EMPTY"
        return
    if line == "EXPORT_ABORTED":
        updates["export_phase"] = "ABORTED"
        return
    if line.startswith("EXPORT_END:"):
        values = _key_values(line.removeprefix("EXPORT_END:"))
        updates["export_phase"] = "COMPLETE"
        if "CHUNKS" in values:
            updates["export_chunks"] = _unsigned(values["CHUNKS"], "CHUNKS")
        if "FRAMES" in values:
            updates["export_frames"] = _unsigned(values["FRAMES"], "FRAMES")
