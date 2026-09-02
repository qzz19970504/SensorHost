from sensor_host.protocol import Frame, MessageType
from sensor_host.tools.dual_output_compare import compare_sensor_frames


def frame(message_type: MessageType, sequence: int, payload: bytes) -> Frame:
    return Frame(
        message_type=message_type,
        flags=0,
        sequence=sequence,
        timestamp_us=sequence * 100,
        item_count=1,
        payload=payload,
    )


def test_matches_sensor_frames_and_ignores_control_order() -> None:
    uart = [
        frame(MessageType.IIS3DWB_FIFO, 1, b"iis"),
        frame(MessageType.JY61PL_SAMPLE, 2, b"jy"),
    ]
    cdc = [
        frame(MessageType.CLI_RESPONSE, 0, b"OK\r\n"),
        frame(MessageType.JY61PL_SAMPLE, 2, b"jy"),
        frame(MessageType.STATUS, 0, bytes(64)),
        frame(MessageType.IIS3DWB_FIFO, 1, b"iis"),
    ]

    result = compare_sensor_frames(uart, cdc)

    assert result.uart_sensor_frames == 2
    assert result.cdc_sensor_frames == 2
    assert result.matched_frames == 2
    assert result.uart_only_sequences == ()
    assert result.cdc_only_sequences == ()
    assert result.content_mismatches == ()


def test_reports_missing_and_same_sequence_content_mismatch() -> None:
    uart = [
        frame(MessageType.IIS3DWB_FIFO, 10, b"a"),
        frame(MessageType.JY61PL_SAMPLE, 11, b"uart"),
    ]
    cdc = [
        frame(MessageType.JY61PL_SAMPLE, 11, b"cdc"),
        frame(MessageType.IIS3DWB_FIFO, 12, b"extra"),
    ]

    result = compare_sensor_frames(uart, cdc)

    assert result.matched_frames == 0
    assert result.uart_only_sequences == (10,)
    assert result.cdc_only_sequences == (12,)
    assert result.content_mismatches == (11,)
