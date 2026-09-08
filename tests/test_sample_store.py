import numpy as np
import pytest

from sensor_host.acquisition import RealtimeSampleStore
from sensor_host.protocol import IisSample, Jy61plSample


def make_iis_sample(timestamp_us: float, raw_x: int) -> IisSample:
    return IisSample(
        timestamp_us=timestamp_us,
        acceleration_raw=(raw_x, -raw_x, raw_x // 2),
        acceleration_g=(
            raw_x * 0.000061,
            -raw_x * 0.000061,
            raw_x * 0.0000305,
        ),
    )


def test_snapshot_keeps_requested_window_and_point_budget() -> None:
    store = RealtimeSampleStore(retention_s=30.0)
    samples = tuple(
        make_iis_sample(sample_index * 1_000.0, sample_index)
        for sample_index in range(20_000)
    )
    store.append_iis(samples)

    snapshot = store.snapshot(window_s=5.0, max_points=800)

    assert snapshot.time_s.size <= 800
    assert snapshot.time_s[0] >= -5.0
    assert snapshot.time_s[-1] == 0.0
    assert np.max(snapshot.x_g) == pytest.approx(19_999 * 0.000061)


def test_latest_orientation_is_reported_with_age() -> None:
    store = RealtimeSampleStore(retention_s=30.0)
    orientation = Jy61plSample(
        raw=(1, 2, 3, 2500, 4, 5, 6),
        acceleration_g=(0.1, 0.2, 0.9),
        temperature_c=25.0,
        angles_deg=(10.0, 20.0, 30.0),
    )
    store.update_jy(orientation, received_monotonic_s=100.0)

    snapshot = store.snapshot(
        window_s=5.0,
        max_points=800,
        now_monotonic_s=100.4,
    )

    assert snapshot.orientation is not None
    assert snapshot.orientation.angles_deg == (10.0, 20.0, 30.0)
    assert snapshot.orientation_age_s == pytest.approx(0.4)


def test_two_point_budget_keeps_oldest_and_latest_visible_samples() -> None:
    store = RealtimeSampleStore(retention_s=30.0)
    samples = tuple(
        make_iis_sample(sample_index * 1_000.0, sample_index)
        for sample_index in range(10)
    )
    store.append_iis(samples)

    snapshot = store.snapshot(window_s=5.0, max_points=2)

    assert snapshot.time_s.size == 2
    assert snapshot.time_s[0] == pytest.approx(-0.009)
    assert snapshot.time_s[-1] == 0.0


def test_clear_samples_discards_history_and_accepts_new_data():
    store = RealtimeSampleStore()
    store.append_iis((make_iis_sample(1000, 5),))
    store.clear_samples()
    assert store.snapshot(10, 100).time_s.size == 0
    store.append_iis((make_iis_sample(2000, 10),))
    snapshot = store.snapshot(10, 100)
    assert snapshot.time_s.size == 1
    assert snapshot.x_g[0] == pytest.approx(10 * 0.000061)
