from pathlib import Path
import uuid

from sensor_host.protocol import MessageType, StreamParser


def test_shared_golden_stream_decodes_in_one_byte_chunks() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    stream = (repository_root / "test" / "golden" / "stream_v1_frames.bin").read_bytes()
    parser = StreamParser()
    frames = []

    for value in stream:
        frames.extend(parser.feed(bytes((value,))))

    assert [frame.message_type for frame in frames] == [
        MessageType.IIS3DWB_FIFO,
        MessageType.JY61PL_SAMPLE,
        MessageType.STATUS,
        MessageType.CLI_RESPONSE,
    ]
    assert [frame.sequence for frame in frames] == [1, 2, 3, 4]
    assert parser.stats.crc_errors == 0
    assert parser.last_sequence == 2
    assert frames[0].device_uuid == uuid.UUID("00112233-4455-6677-8899-aabbccddeeff")
    assert frames[1].device_uuid == frames[0].device_uuid
    assert frames[2].device_uuid is None


def test_reset_session_clears_sequence_baseline_and_partial_bytes() -> None:
    parser = StreamParser()
    parser.feed(b"SDF")

    parser.reset_session()

    assert parser.buffered_bytes == 0
    assert parser.last_sequence is None
