"""Measure GUI snapshot-callback latency for the UI-09 performance budget.

Drives ``MainWindow.update_snapshot`` at the 33 ms display cadence with a
bounded synthetic snapshot and records per-callback durations so the plan's
section 7.3 budget (single-node GUI callback p95 <= 33 ms) can be checked over
a long run, e.g. ``--minutes 30``.  This measures the display path only; it
does not synthesize the full 26.667 kHz wire stream.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from sensor_host.acquisition import UiSnapshot
from sensor_host.presentation import MainWindow, dark_stylesheet, load_application_fonts
from sensor_host.protocol import ParserStats


_P95_BUDGET_MS = 33.0


def _snapshot(points: int, window_s: float) -> UiSnapshot:
    time_s = np.linspace(-window_s, 0.0, points, dtype=np.float64)
    return UiSnapshot(
        time_s=time_s,
        x_g=0.18 * np.sin(2.0 * np.pi * 18.0 * time_s),
        y_g=0.11 * np.sin(2.0 * np.pi * 27.0 * time_s + 0.7),
        z_g=0.24 * np.sin(2.0 * np.pi * 42.0 * time_s + 1.2),
        orientation=None,
        orientation_age_s=None,
        firmware_status=None,
        parser_stats=ParserStats(frames=points),
        sample_rate_hz=26_666.7,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=30.0)
    parser.add_argument("--points", type=int, default=5_000)
    parser.add_argument("--window", type=float, default=10.0)
    parser.add_argument(
        "--output", type=Path, default=Path("build/ui-review/ui-perf.csv")
    )
    arguments = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication(sys.argv)
    load_application_fonts()
    application.setStyleSheet(dark_stylesheet())
    window = MainWindow()
    window.show()

    durations_ms: list[float] = []
    snapshot = _snapshot(arguments.points, arguments.window)
    original_update = window.update_snapshot

    def timed_update(snapshot_obj: UiSnapshot) -> None:
        started = time.perf_counter()
        original_update(snapshot_obj)
        durations_ms.append((time.perf_counter() - started) * 1_000.0)

    window.update_snapshot = timed_update  # type: ignore[method-assign]

    timer = QTimer()
    timer.setInterval(33)
    timer.timeout.connect(lambda: window.update_snapshot(snapshot))
    timer.start()

    deadline = time.monotonic() + arguments.minutes * 60.0
    while time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.001)
    timer.stop()

    if not durations_ms:
        print("no callback samples collected")
        return 1
    ordered = sorted(durations_ms)
    p50 = ordered[int(0.50 * (len(ordered) - 1))]
    p95 = ordered[int(0.95 * (len(ordered) - 1))]
    try:
        import psutil  # optional dependency

        rss_mb = psutil.Process(os.getpid()).memory_info().rss / 1e6
    except Exception:  # pragma: no cover - psutil optional
        rss_mb = float("nan")

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("w", encoding="utf-8") as handle:
        handle.write("metric,value\n")
        handle.write(f"minutes,{arguments.minutes}\n")
        handle.write(f"points,{arguments.points}\n")
        handle.write(f"count,{len(ordered)}\n")
        handle.write(f"p50_ms,{p50:.3f}\n")
        handle.write(f"p95_ms,{p95:.3f}\n")
        handle.write(f"max_ms,{ordered[-1]:.3f}\n")
        handle.write(f"rss_mb,{rss_mb:.1f}\n")
    print(
        f"count={len(ordered)} p50={p50:.3f}ms p95={p95:.3f}ms "
        f"max={ordered[-1]:.3f}ms rss={rss_mb:.1f}MB"
    )
    verdict = "PASS" if p95 <= _P95_BUDGET_MS else "FAIL"
    print(f"single-node GUI callback p95 <= {_P95_BUDGET_MS:.0f}ms -> {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
