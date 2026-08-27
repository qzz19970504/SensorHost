import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_firmware_reserves_small_buffers_for_status_bursts() -> None:
    source = (REPOSITORY_ROOT / "app" / "Transport" / "transport.c").read_text(
        encoding="utf-8"
    )
    match = re.search(r"#define\s+TRANSPORT_SMALL_BUFFER_COUNT\s+(\d+)U", source)

    assert match is not None
    assert int(match.group(1)) >= 8
