import numpy as np
import pytest

from sensor_host.presentation.orientation_view import (
    rotation_matrix_zyx,
    world_acceleration,
)


def test_positive_yaw_rotates_local_x_to_world_y() -> None:
    rotation = rotation_matrix_zyx(
        roll_deg=0.0,
        pitch_deg=0.0,
        yaw_deg=90.0,
    )

    rotated_axis = rotation @ np.array([1.0, 0.0, 0.0])

    assert rotated_axis == pytest.approx([0.0, 1.0, 0.0], abs=1e-7)


def test_acceleration_vector_rotates_with_device() -> None:
    vector = world_acceleration(
        acceleration_g=(1.0, 0.0, 0.0),
        angles_deg=(0.0, 0.0, 90.0),
    )

    assert vector == pytest.approx((0.0, 1.0, 0.0), abs=1e-7)
