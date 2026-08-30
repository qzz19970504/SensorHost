"""Metadata helpers shared by tests and the Windows packaging workflow."""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PROJECT_DISTRIBUTION = "stm32-sensor-host"
SOURCE_VERSION = "0.1.0"
ARTIFACT_PREFIX = "STM32SensorHost"
ARTIFACT_PLATFORM = "win64"
MANIFEST_ENCODING = "utf-8"


def project_version() -> str:
    """Return the installed package version, or the source-tree version."""
    try:
        return version(PROJECT_DISTRIBUTION)
    except PackageNotFoundError:
        return SOURCE_VERSION


def artifact_name() -> str:
    """Return the versioned Windows x64 executable filename."""
    return f"{ARTIFACT_PREFIX}-{project_version()}-{ARTIFACT_PLATFORM}.exe"


def write_manifest(artifact: Path) -> Path:
    """Write size and SHA-256 metadata next to an existing artifact."""
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest_path = artifact.with_suffix(".json")
    payload = {
        "artifact": artifact.name,
        "bytes": artifact.stat().st_size,
        "sha256": digest,
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding=MANIFEST_ENCODING,
    )
    return manifest_path
