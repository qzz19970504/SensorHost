"""Self-contained STM32 SD-staged OTA upload support for the sensor host.

The wire contract (OTAF frames, ``.ota`` manifest layout and ``+OTA:`` reply
text) mirrors the firmware repository, but nothing here imports it: the host
carries its own codec, package validation, stream demultiplexer and uploader
state machine together with their own test vectors.
"""

from .codec import (
    BEGIN_PAYLOAD_SIZE,
    FRAME_CRC_SIZE,
    FRAME_HEADER_SIZE,
    FRAME_MAGIC,
    FRAME_MAX_PAYLOAD,
    FRAME_MAX_SIZE,
    FRAME_VERSION,
    DeviceResponse,
    FrameType,
    OtaCodecError,
    UploadFrame,
    decode_frame,
    encode_frame,
    parse_ready,
    parse_response,
)
from .demux import StreamDemultiplexer
from .messages import NACK_CODE_ZH, describe_nack, describe_phase
from .package import (
    MANIFEST_BLOCK_SIZE,
    MANIFEST_HEADER_SIZE,
    APP_FLASH_SIZE,
    MIN_APP_IMAGE_SIZE,
    STATE_PACKAGE,
    TARGET_ID,
    OtaPackage,
    OtaPackageError,
    build_package,
    format_crc,
    format_version,
    is_package_image,
    load_image_or_package,
    load_package,
    pack_manifest,
    pack_ota,
    parse_manifest,
    validate_package,
    version_from_text,
)
from .uploader import (
    OtaUploadCancelled,
    OtaUploadError,
    OtaUploader,
    UploadTransport,
)

__all__ = [
    "BEGIN_PAYLOAD_SIZE",
    "FRAME_CRC_SIZE",
    "FRAME_HEADER_SIZE",
    "FRAME_MAGIC",
    "FRAME_MAX_PAYLOAD",
    "FRAME_MAX_SIZE",
    "FRAME_VERSION",
    "APP_FLASH_SIZE",
    "MANIFEST_BLOCK_SIZE",
    "MANIFEST_HEADER_SIZE",
    "MIN_APP_IMAGE_SIZE",
    "NACK_CODE_ZH",
    "DeviceResponse",
    "FrameType",
    "OtaCodecError",
    "OtaPackage",
    "OtaPackageError",
    "OtaUploadCancelled",
    "OtaUploadError",
    "OtaUploader",
    "STATE_PACKAGE",
    "StreamDemultiplexer",
    "TARGET_ID",
    "UploadFrame",
    "UploadTransport",
    "build_package",
    "decode_frame",
    "describe_nack",
    "describe_phase",
    "encode_frame",
    "format_crc",
    "format_version",
    "is_package_image",
    "load_image_or_package",
    "load_package",
    "pack_manifest",
    "pack_ota",
    "parse_manifest",
    "parse_ready",
    "parse_response",
    "validate_package",
    "version_from_text",
]
