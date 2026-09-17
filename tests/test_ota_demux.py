"""Stream-demultiplexer regression: SDF1 binary and bare +OTA lines interleave.

The firmware CLI_RESPONSE payload legitimately contains ``OK\\r\\n``; the demux
must hand whole SDF1 frames to the parser untouched and claim only bare
``+OTA:``/``OK`` lines, so ``bytes_discarded`` never grows because of OTA text.
"""

from __future__ import annotations

import struct
import zlib

from sensor_host.ota.demux import StreamDemultiplexer
from sensor_host.protocol.sdf1 import MessageType, StreamParser


def encode_cli_frame(text: str, sequence: int = 1) -> bytes:
    payload = text.encode()
    header = struct.pack(
        "<4sBBHHHIQHH",
        b"SDF1",
        1,
        int(MessageType.CLI_RESPONSE),
        0,
        28,
        len(payload),
        sequence,
        100,
        1,
        0,
    )
    content = header + payload
    return content + struct.pack("<I", zlib.crc32(content) & 0xFFFFFFFF)


def _interleaved_stream() -> tuple[bytes, bytes, list[bytes]]:
    frame_one = encode_cli_frame("+STATE:IDLE\r\nOK\r\n", sequence=1)
    frame_two = encode_cli_frame("+SD:USED=64,READY=1\r\nOK\r\n", sequence=2)
    stream = (
        frame_one
        + b"+OTA:ACK,SEQ=1,NEXT=512\r\n"
        + frame_two
        + b"+OTA:NACK,CODE=OFFSET,SEQ=2,NEXT=512\r\n"
        + b"OK\r\n"
    )
    expected_lines = [
        b"+OTA:ACK,SEQ=1,NEXT=512",
        b"+OTA:NACK,CODE=OFFSET,SEQ=2,NEXT=512",
        b"OK",
    ]
    return stream, frame_one + frame_two, expected_lines


def test_single_feed_separates_frames_and_ota_lines() -> None:
    stream, frames, expected_lines = _interleaved_stream()
    demux = StreamDemultiplexer()
    parser = StreamParser()

    ota_lines, parser_bytes = demux.feed(stream)
    decoded = parser.feed(parser_bytes)

    assert ota_lines == expected_lines
    assert parser_bytes == frames
    assert [frame.cli_text for frame in decoded] == [
        "+STATE:IDLE\r\nOK\r\n",
        "+SD:USED=64,READY=1\r\nOK\r\n",
    ]
    assert parser.stats.frames == 2
    assert parser.stats.bytes_discarded == 0
    assert parser.stats.crc_errors == 0
    assert demux.buffered_bytes == 0


def test_embedded_ok_in_cli_payload_is_not_claimed() -> None:
    # The CLI payload ends with a bare OK\r\n; it must stay inside the frame.
    stream = encode_cli_frame("OK\r\n", sequence=1) + b"+OTA:ACK,SEQ=0,NEXT=0\r\n"
    demux = StreamDemultiplexer()
    parser = StreamParser()

    ota_lines, parser_bytes = demux.feed(stream)
    decoded = parser.feed(parser_bytes)

    assert ota_lines == [b"+OTA:ACK,SEQ=0,NEXT=0"]
    assert len(decoded) == 1
    assert decoded[0].cli_text == "OK\r\n"
    assert parser.stats.bytes_discarded == 0


def test_byte_by_byte_feed_preserves_both_sides() -> None:
    stream, frames, expected_lines = _interleaved_stream()
    demux = StreamDemultiplexer()
    parser = StreamParser()

    collected_lines: list[bytes] = []
    for index in range(len(stream)):
        lines, parser_bytes = demux.feed(stream[index : index + 1])
        collected_lines.extend(lines)
        parser.feed(parser_bytes)

    assert collected_lines == expected_lines
    assert parser.stats.frames == 2
    assert parser.stats.bytes_discarded == 0
    assert [frame.cli_text for frame in parser.feed(b"")] == []


def test_arbitrary_chunk_split_holds_partial_frame() -> None:
    frame = encode_cli_frame("+STATE:ACQUIRE\r\nOK\r\n", sequence=3)
    demux = StreamDemultiplexer()
    parser = StreamParser()

    # Feed a partial frame: nothing may reach the parser yet.
    lines, parser_bytes = demux.feed(frame[:10])
    assert lines == []
    assert parser_bytes == b""
    assert demux.buffered_bytes == 10

    lines, parser_bytes = demux.feed(frame[10:] + b"+OTA:STAGED,VERSION=1.0.0,CRC=DEADBEEF\r\n")
    decoded = parser.feed(parser_bytes)

    assert lines == [b"+OTA:STAGED,VERSION=1.0.0,CRC=DEADBEEF"]
    assert parser_bytes == frame
    assert len(decoded) == 1
    assert parser.stats.bytes_discarded == 0


def test_oversized_text_residue_is_flushed_to_parser() -> None:
    demux = StreamDemultiplexer(max_line=16)
    parser = StreamParser()

    # A '+'-prefixed run with no newline can never become a bounded OTA line;
    # the safeguard must release it so the stream is never starved.
    lines, parser_bytes = demux.feed(b"+" + b"x" * 40)

    assert lines == []
    assert parser_bytes == b"+" + b"x" * 40
    assert demux.buffered_bytes == 0
    # Garbage text is discarded by the parser, which is the expected outcome.
    parser.feed(parser_bytes)
    assert parser.stats.bytes_discarded > 0


def test_reset_clears_held_residue() -> None:
    demux = StreamDemultiplexer()
    demux.feed(b"+OTA:ACK,SEQ=1")
    assert demux.buffered_bytes > 0

    demux.reset()

    assert demux.buffered_bytes == 0
