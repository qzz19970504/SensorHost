import json
from pathlib import Path

from sensor_host.storage import RawSessionRecorder, replay_chunks


def test_recorder_preserves_exact_input_and_writes_metadata(
    tmp_path: Path,
) -> None:
    recording_path = tmp_path / "session.sdf1"
    recorder = RawSessionRecorder(queue_capacity_bytes=1024)
    recorder.start(recording_path, {"protocol": "SDF1", "version": 1})

    assert recorder.submit(b"SDF") is True
    assert recorder.submit(b"1-payload") is True
    summary = recorder.stop()

    assert recording_path.read_bytes() == b"SDF1-payload"
    metadata = json.loads(
        recording_path.with_suffix(".json").read_text(encoding="utf-8")
    )
    assert metadata["bytes_written"] == len(b"SDF1-payload")
    assert summary.bytes_written == len(b"SDF1-payload")
    assert b"".join(replay_chunks(recording_path, chunk_size=3)) == b"SDF1-payload"


def test_oversized_chunk_stops_recording_without_blocking(tmp_path: Path) -> None:
    recorder = RawSessionRecorder(queue_capacity_bytes=4)
    recorder.start(tmp_path / "overflow.sdf1", {})

    assert recorder.submit(b"12345") is False
    assert recorder.failure == "recording queue capacity exceeded"
    summary = recorder.stop()

    assert summary.failure == "recording queue capacity exceeded"
