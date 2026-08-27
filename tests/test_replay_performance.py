import time

from sensor_host.protocol import StreamParser


def test_parser_replays_two_megabytes_faster_than_realtime(
    golden_stream: bytes,
) -> None:
    repeat_count = (2_000_000 // len(golden_stream)) + 1
    payload = (golden_stream * repeat_count)[:2_000_000]
    parser = StreamParser()

    started = time.perf_counter()
    for offset in range(0, len(payload), 4096):
        parser.feed(payload[offset : offset + 4096])
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0
    assert parser.stats.crc_errors == 0
