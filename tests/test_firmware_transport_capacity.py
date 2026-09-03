import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TRANSPORT_DIR = REPOSITORY_ROOT / "app" / "Transport"


def _read(filename: str) -> str:
    return (TRANSPORT_DIR / filename).read_text(encoding="utf-8")


def test_iis_live_uses_dual_slot_newest_wins() -> None:
    """IIS live buffer must be a 2-slot array (newest-wins design)."""
    source = _read("transport.h")
    match = re.search(r"live_iis\[(\d+)\]", source)
    assert match is not None, "live_iis array not found in transport.h"
    assert int(match.group(1)) == 2


def test_jy_live_queue_depth_at_least_four() -> None:
    """JY live FIFO must have at least 4 slots."""
    source = _read("live_queue_core.h")
    match = re.search(r"#define\s+JY_LIVE_QUEUE_DEPTH\s+(\d+)U", source)
    assert match is not None
    assert int(match.group(1)) >= 4


def test_control_buffer_count_at_least_eight() -> None:
    """Control TX pool must reserve >= 8 buffers for CLI responses."""
    source = _read("transport.c")
    match = re.search(
        r"#define\s+TRANSPORT_CONTROL_BUFFER_COUNT\s+(\d+)U", source
    )
    assert match is not None
    assert int(match.group(1)) >= 8


def test_frame_pool_buffer_count_at_least_eight() -> None:
    """Shared frame pool must have >= 8 buffers for storage + live."""
    source = _read("frame_pool.h")
    match = re.search(r"#define\s+FRAME_POOL_BUFFER_COUNT\s+(\d+)U", source)
    assert match is not None
    assert int(match.group(1)) >= 8


def test_no_obsolete_small_buffer_or_cdc_mirror() -> None:
    """Obsolete TRANSPORT_SMALL_BUFFER_COUNT and CDC mirror must be gone."""
    for name in ("transport.c", "transport.h", "transport_core.c",
                 "transport_core.h"):
        source = _read(name)
        assert "TRANSPORT_SMALL_BUFFER_COUNT" not in source, (
            f"obsolete macro in {name}"
        )
        assert "cdc_mirror" not in source, f"CDC mirror residual in {name}"
        assert "BeginCdcMirror" not in source, (
            f"BeginCdcMirror residual in {name}"
        )
