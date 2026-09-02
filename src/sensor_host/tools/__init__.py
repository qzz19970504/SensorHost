"""Hardware acceptance models shared by command-line tools and tests."""

from .acceptance_models import AcceptanceReport
from .dual_output_compare import DualOutputResult, compare_sensor_frames

__all__ = ["AcceptanceReport", "DualOutputResult", "compare_sensor_frames"]
