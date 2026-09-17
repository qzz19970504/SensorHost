"""Unit tests for OTA package loading, manifest validation, and formatting."""

from __future__ import annotations

import struct
import zlib

import pytest

from sensor_host.ota.package import (
    MANIFEST_BLOCK_SIZE,
    MANIFEST_CRC_OFFSET,
    STATE_PACKAGE,
    STATE_READY,
    TARGET_ID,
    OtaPackageError,
    format_crc,
    format_version,
    load_package,
    pack_manifest,
    pack_ota,
    parse_manifest,
    validate_package,
)


def _image(size: int = 4096) -> bytes:
    return bytes((index * 7 + 3) & 0xFF for index in range(size))


def test_pack_and_validate_roundtrip() -> None:
    image = _image()
    package = pack_ota(image=image, app_version="1.2.3")

    manifest = validate_package(package)

    assert manifest["state"] == STATE_PACKAGE
    assert manifest["target_id"] == TARGET_ID
    assert manifest["image_size"] == len(image)
    assert manifest["image_crc32"] == zlib.crc32(image) & 0xFFFFFFFF
    assert manifest["app_version"] == (1 << 24) | (2 << 16) | 3
    assert len(package) == MANIFEST_BLOCK_SIZE + len(image)


def test_format_version_and_crc() -> None:
    assert format_version((1 << 24) | (2 << 16) | 3) == "1.2.3"
    assert format_version(0x00010002) == "0.1.2"
    assert format_crc(0x0A1B2C3D) == "0A1B2C3D"
    assert format_crc(0x1) == "00000001"


def test_load_package_reads_validated_file(tmp_path) -> None:
    image = _image(2048)
    path = tmp_path / "app.ota"
    path.write_bytes(pack_ota(image=image, app_version="0.9.1"))

    loaded = load_package(path)

    assert loaded.image == image
    assert loaded.image_size == 2048
    assert loaded.version_text == "0.9.1"
    assert loaded.crc_text == format_crc(loaded.image_crc32)
    assert loaded.begin_payload == loaded.manifest_block[:80]


def test_load_package_rejects_wrong_suffix(tmp_path) -> None:
    path = tmp_path / "app.bin"
    path.write_bytes(pack_ota(image=_image(), app_version="1.0.0"))
    with pytest.raises(OtaPackageError):
        load_package(path)


def test_validate_rejects_truncated_package() -> None:
    with pytest.raises(OtaPackageError):
        validate_package(b"\x00" * (MANIFEST_BLOCK_SIZE - 1))


def test_validate_rejects_non_package_state() -> None:
    image = _image()
    package = pack_ota(image=image, app_version="1.0.0", state=STATE_READY)
    with pytest.raises(OtaPackageError, match="PACKAGE state"):
        validate_package(package)


def test_validate_rejects_wrong_target_id() -> None:
    image = _image()
    package = bytearray(pack_ota(image=image, app_version="1.0.0"))
    package[16:32] = b"OTHER-TARGET\0\0\0\0"
    # Repair the manifest CRC so the target check (not the CRC) rejects it.
    struct.pack_into(
        "<I",
        package,
        MANIFEST_CRC_OFFSET,
        zlib.crc32(bytes(package[:MANIFEST_CRC_OFFSET])) & 0xFFFFFFFF,
    )
    with pytest.raises(OtaPackageError, match="target ID"):
        validate_package(bytes(package))


def test_validate_rejects_image_crc_mismatch() -> None:
    image = _image()
    package = bytearray(pack_ota(image=image, app_version="1.0.0"))
    package[-1] ^= 0x5A  # tamper the image, keep the manifest CRC untouched
    with pytest.raises(OtaPackageError, match="image CRC"):
        validate_package(bytes(package))


def test_validate_rejects_image_length_mismatch() -> None:
    image = _image()
    package = pack_ota(image=image, app_version="1.0.0")
    with pytest.raises(OtaPackageError, match="image length"):
        validate_package(package[:-1])


def test_parse_manifest_rejects_nonzero_reserved() -> None:
    block = bytearray(pack_manifest(image=_image(), app_version="1.0.0",
                                    minimum_bootloader_version="1.0.0"))
    block[0x100] = 0xFF
    struct.pack_into(
        "<I",
        block,
        MANIFEST_CRC_OFFSET,
        zlib.crc32(bytes(block[:MANIFEST_CRC_OFFSET])) & 0xFFFFFFFF,
    )
    with pytest.raises(OtaPackageError, match="reserved"):
        parse_manifest(bytes(block))


def test_parse_manifest_rejects_bad_magic_and_crc() -> None:
    block = pack_manifest(image=_image(), app_version="1.0.0",
                          minimum_bootloader_version="1.0.0")
    bad_magic = bytearray(block)
    bad_magic[0] = ord("X")
    with pytest.raises(OtaPackageError, match="magic"):
        parse_manifest(bytes(bad_magic))

    bad_crc = bytearray(block)
    bad_crc[MANIFEST_CRC_OFFSET] ^= 0xFF
    with pytest.raises(OtaPackageError, match="CRC"):
        parse_manifest(bytes(bad_crc))
