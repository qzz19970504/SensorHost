"""OTA package (``.ota``) loading, manifest validation, and test-vector packing.

The 512-byte manifest layout and image CRC contract mirror the firmware's
``tools/package_ota.py``; this module is self-contained and never imports the
firmware repository.  ``pack_manifest``/``pack_ota`` exist so the host test
suite can build its own golden packages without a hardware toolchain.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


MANIFEST_MAGIC = b"OTA1"
MANIFEST_FORMAT_VERSION = 1
MANIFEST_HEADER_SIZE = 80
MANIFEST_BLOCK_SIZE = 512
MANIFEST_CRC_OFFSET = 508
MANIFEST_HEADER_RESERVED_OFFSET = 0x48
TARGET_ID = b"F407VE-JY-I3DWB\0"
TARGET_ID_SIZE = 16
MCU_DEVICE_ID = 0x413
PROTOCOL_VERSION = 1
PACKAGE_ID_SIZE = 12
APP_FLASH_START = 0x08010000
APP_FLASH_SIZE = 0x08060000 - APP_FLASH_START
MIN_APP_IMAGE_SIZE = 8

STATE_PACKAGE = 0
STATE_RECEIVING = 1
STATE_READY = 2
STATE_INSTALLING = 3
STATE_APPLIED = 4

_STATE_NAMES = {
    STATE_PACKAGE: "PACKAGE",
    STATE_RECEIVING: "RECEIVING",
    STATE_READY: "READY",
    STATE_INSTALLING: "INSTALLING",
    STATE_APPLIED: "APPLIED",
}


class OtaPackageError(ValueError):
    """Report an invalid or unsupported OTA package."""


@dataclass(frozen=True)
class OtaPackage:
    """Hold a validated package plus its decoded manifest summary."""

    data: bytes
    manifest: dict[str, Any]

    @property
    def image(self) -> bytes:
        """Return the raw application image bytes after the 512-byte header."""
        return self.data[MANIFEST_BLOCK_SIZE:]

    @property
    def manifest_block(self) -> bytes:
        """Return the 512-byte manifest block used as the BEGIN payload source."""
        return self.data[:MANIFEST_BLOCK_SIZE]

    @property
    def begin_payload(self) -> bytes:
        """Return the first 80 bytes of the manifest sent in the BEGIN frame."""
        return self.manifest_block[:MANIFEST_HEADER_SIZE]

    @property
    def image_size(self) -> int:
        return int(self.manifest["image_size"])

    @property
    def image_crc32(self) -> int:
        return int(self.manifest["image_crc32"])

    @property
    def app_version(self) -> int:
        return int(self.manifest["app_version"])

    @property
    def version_text(self) -> str:
        return format_version(self.app_version)

    @property
    def crc_text(self) -> str:
        return format_crc(self.image_crc32)


def format_version(app_version: int) -> str:
    """Render a packed ``major<<24|minor<<16|patch`` value as ``a.b.c``."""
    major = (app_version >> 24) & 0xFF
    minor = (app_version >> 16) & 0xFF
    patch = app_version & 0xFFFF
    return f"{major}.{minor}.{patch}"


def format_crc(image_crc32: int) -> str:
    """Render an image CRC32 as the eight-digit uppercase hex the firmware uses."""
    return f"{image_crc32 & 0xFFFFFFFF:08X}"


def version_value(value: int | str | Sequence[int]) -> int:
    """Coerce a version int/``a.b.c`` string/triple into its packed 32-bit form."""
    if isinstance(value, int):
        if not 0 <= value <= 0xFFFFFFFF:
            raise OtaPackageError("version must fit in 32 bits")
        return value
    if isinstance(value, str):
        parts = value.split(".")
        if len(parts) != 3:
            raise OtaPackageError("version must be major.minor.patch")
        try:
            value = tuple(int(part, 0) for part in parts)
        except ValueError as error:
            raise OtaPackageError("version must contain decimal fields") from error
    if len(value) != 3:
        raise OtaPackageError("version must contain major, minor and patch")
    major, minor, patch = (int(part) for part in value)
    if not 0 <= major <= 0xFF:
        raise OtaPackageError("major version exceeds 8 bits")
    if not 0 <= minor <= 0xFF:
        raise OtaPackageError("minor version exceeds 8 bits")
    if not 0 <= patch <= 0xFFFF:
        raise OtaPackageError("patch version exceeds 16 bits")
    return (major << 24) | (minor << 16) | patch


def parse_manifest(block: bytes) -> dict[str, Any]:
    """Validate one 512-byte manifest block and return its decoded fields."""
    if len(block) != MANIFEST_BLOCK_SIZE:
        raise OtaPackageError("manifest block must be 512 bytes")
    if block[0:4] != MANIFEST_MAGIC:
        raise OtaPackageError("manifest magic is invalid")
    format_version_value, header_size = struct.unpack_from("<HH", block, 4)
    if format_version_value != MANIFEST_FORMAT_VERSION:
        raise OtaPackageError("manifest format version is invalid")
    if header_size != MANIFEST_HEADER_SIZE:
        raise OtaPackageError("manifest header size is invalid")
    expected_crc = struct.unpack_from("<I", block, MANIFEST_CRC_OFFSET)[0]
    actual_crc = zlib.crc32(block[:MANIFEST_CRC_OFFSET]) & 0xFFFFFFFF
    if expected_crc != actual_crc:
        raise OtaPackageError("manifest CRC is invalid")
    if any(block[MANIFEST_HEADER_RESERVED_OFFSET: MANIFEST_CRC_OFFSET]):
        raise OtaPackageError("manifest reserved bytes must be zero")
    generation, state = struct.unpack_from("<II", block, 8)
    device_id, minimum_bootloader_version, app_version, app_address, image_size = (
        struct.unpack_from("<IIIII", block, 32)
    )
    image_crc32, protocol_version, flags = struct.unpack_from("<IHH", block, 52)
    if block[16:32] != TARGET_ID:
        raise OtaPackageError("manifest target ID is invalid")
    if device_id != MCU_DEVICE_ID:
        raise OtaPackageError("manifest device ID is invalid")
    if app_address != APP_FLASH_START:
        raise OtaPackageError("manifest application address is invalid")
    if not MIN_APP_IMAGE_SIZE <= image_size <= APP_FLASH_SIZE:
        raise OtaPackageError("manifest image size is invalid")
    if protocol_version != PROTOCOL_VERSION or flags != 0:
        raise OtaPackageError("manifest protocol fields are invalid")
    if not STATE_PACKAGE <= state <= STATE_APPLIED:
        raise OtaPackageError("manifest state is invalid")
    return {
        "generation": generation,
        "state": state,
        "state_name": _STATE_NAMES.get(state, str(state)),
        "target_id": bytes(block[16:32]),
        "device_id": device_id,
        "minimum_bootloader_version": minimum_bootloader_version,
        "app_version": app_version,
        "app_address": app_address,
        "image_size": image_size,
        "image_crc32": image_crc32,
        "protocol_version": protocol_version,
        "flags": flags,
        "package_id": bytes(block[60:72]),
    }


def validate_package(package: bytes) -> dict[str, Any]:
    """Run every pre-send self-check on a raw package and return its manifest.

    Rejects truncated packages, non-PACKAGE states, mismatched target IDs, an
    image length that disagrees with the manifest, and image CRC mismatches.
    """
    if len(package) < MANIFEST_BLOCK_SIZE:
        raise OtaPackageError("OTA package is truncated")
    manifest = parse_manifest(package[:MANIFEST_BLOCK_SIZE])
    if manifest["state"] != STATE_PACKAGE:
        raise OtaPackageError(
            f"OTA package header is not in PACKAGE state (state={manifest['state_name']})"
        )
    if manifest["target_id"] != TARGET_ID:
        raise OtaPackageError("OTA package target does not match the device")
    image = package[MANIFEST_BLOCK_SIZE:]
    if len(image) != manifest["image_size"]:
        raise OtaPackageError("OTA package image length does not match manifest")
    if (zlib.crc32(image) & 0xFFFFFFFF) != manifest["image_crc32"]:
        raise OtaPackageError("OTA package image CRC is invalid")
    return manifest


def load_package(path: str | Path) -> OtaPackage:
    """Load, self-check and wrap one ``.ota`` package file."""
    package_path = Path(path)
    if package_path.suffix.lower() != ".ota":
        raise OtaPackageError("uploader accepts only .ota package files")
    try:
        package = package_path.read_bytes()
    except OSError as error:
        raise OtaPackageError(f"cannot read OTA package: {error}") from error
    manifest = validate_package(package)
    return OtaPackage(data=package, manifest=manifest)


def pack_manifest(
    *,
    image: bytes,
    app_version: int | str | Sequence[int],
    minimum_bootloader_version: int | str | Sequence[int],
    generation: int = 0,
    state: int = STATE_PACKAGE,
    image_size: int | None = None,
    image_crc32: int | None = None,
    package_id: bytes | None = None,
    app_address: int = APP_FLASH_START,
) -> bytes:
    """Build one 512-byte manifest block (test vector helper)."""
    if not isinstance(image, bytes):
        raise OtaPackageError("image must be bytes")
    effective_size = len(image) if image_size is None else int(image_size)
    if effective_size != len(image):
        raise OtaPackageError("image size does not match image bytes")
    if effective_size < MIN_APP_IMAGE_SIZE:
        raise OtaPackageError("image size is below the minimum")
    if effective_size > APP_FLASH_SIZE:
        raise OtaPackageError("image size exceeds the application region")
    if app_address != APP_FLASH_START:
        raise OtaPackageError("application address must be 0x08010000")
    if not 0 <= generation <= 0xFFFFFFFF:
        raise OtaPackageError("generation must fit in 32 bits")
    if not STATE_PACKAGE <= state <= STATE_APPLIED:
        raise OtaPackageError("manifest state is invalid")
    effective_crc = (
        zlib.crc32(image) & 0xFFFFFFFF if image_crc32 is None else int(image_crc32)
    )
    if not 0 <= effective_crc <= 0xFFFFFFFF:
        raise OtaPackageError("image CRC must fit in 32 bits")
    effective_package_id = (
        hashlib.sha256(image).digest()[:PACKAGE_ID_SIZE]
        if package_id is None
        else bytes(package_id)
    )
    if len(effective_package_id) != PACKAGE_ID_SIZE:
        raise OtaPackageError("package ID must be 12 bytes")

    block = bytearray(MANIFEST_BLOCK_SIZE)
    block[0:4] = MANIFEST_MAGIC
    struct.pack_into("<HH", block, 4, MANIFEST_FORMAT_VERSION, MANIFEST_HEADER_SIZE)
    struct.pack_into("<II", block, 8, generation, state)
    block[16:32] = TARGET_ID
    struct.pack_into(
        "<IIIII",
        block,
        32,
        MCU_DEVICE_ID,
        version_value(minimum_bootloader_version),
        version_value(app_version),
        app_address,
        effective_size,
    )
    struct.pack_into("<IHH", block, 52, effective_crc, PROTOCOL_VERSION, 0)
    block[60:72] = effective_package_id
    struct.pack_into(
        "<I",
        block,
        MANIFEST_CRC_OFFSET,
        zlib.crc32(block[:MANIFEST_CRC_OFFSET]) & 0xFFFFFFFF,
    )
    return bytes(block)


def pack_ota(
    *,
    image: bytes,
    app_version: int | str | Sequence[int],
    minimum_bootloader_version: int | str | Sequence[int] = "1.0.0",
    generation: int = 0,
    image_crc32: int | None = None,
    state: int = STATE_PACKAGE,
) -> bytes:
    """Assemble a complete ``512 + image`` package (test vector helper)."""
    header = pack_manifest(
        image=image,
        app_version=app_version,
        minimum_bootloader_version=minimum_bootloader_version,
        generation=generation,
        state=state,
        image_crc32=image_crc32,
    )
    return header + image
