from sensor_host.tools.acceptance_models import AcceptanceReport


def test_acceptance_report_requires_zero_integrity_errors() -> None:
    report = AcceptanceReport(
        duration_s=1800.0,
        bytes_received=350_000_000,
        frames=100_000,
        crc_errors=0,
        sequence_gaps=0,
        source_drop_delta=0,
        transport_drop_delta=0,
        fifo_overrun_delta=0,
        recorder_bytes=350_000_000,
        replay_frames=100_000,
    )

    assert report.passed
    assert not report.with_updates(crc_errors=1).passed
    assert not report.with_updates(replay_crc_errors=1).passed
    assert not report.with_updates(replay_frames=99_999).passed


def test_acceptance_report_requires_lossless_recording() -> None:
    report = AcceptanceReport(
        duration_s=300.0,
        bytes_received=10_000,
        frames=100,
        crc_errors=0,
        sequence_gaps=0,
        source_drop_delta=0,
        transport_drop_delta=0,
        fifo_overrun_delta=0,
        recorder_bytes=9_999,
        replay_frames=100,
    )

    assert not report.passed
