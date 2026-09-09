"""User-facing application branding and icon resources."""

from pathlib import Path


APPLICATION_NAME = "Vibration Sensor Host"
APPLICATION_BRAND = "VIBRATION SENSOR DESKTOP"
VIBRATION_SENSOR_LABEL = "VIBRATION SENSOR"
ORIENTATION_SENSOR_LABEL = "Orientation Sensor"
ORIENTATION_WAITING_MESSAGE = "WAITING FOR ORIENTATION DATA"
APPLICATION_ICON_PATH = (
    Path(__file__).resolve().parent / "assets" / "vibration_sensor_icon.png"
)
