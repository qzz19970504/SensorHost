"""Writable application data paths independent of checkout and launch directory."""

import os
from pathlib import Path


def data_root() -> Path:
    """Use an explicit override or the user's persistent application directory."""
    override = os.environ.get("SENSOR_HOST_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home() / ".local" / "share") / "SensorHost"
