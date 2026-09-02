# Host UI Soft Metrics and Display Kalman Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved soft-tile visual treatment, align dashboard typography, replace the orientation status strip with an overlay, and add an optional display-only three-axis scalar Kalman filter without changing raw recording or the wire protocol.

**Architecture:** Keep filtering in the acquisition sample store so each incoming sample is filtered once before display envelope selection; retain raw and filtered bounded chunks side by side. The application controller owns the display-mode preference, while presentation widgets only emit intent and render snapshots. Visual changes remain role/property driven through the existing Qt stylesheet.

**Tech Stack:** Python 3.12, PyQt6, NumPy, pyqtgraph, pytest, pytest-qt, PyInstaller

---

### Task 1: Scalar three-axis Kalman filter

**Files:**
- Create: `host/src/sensor_host/acquisition/display_filter.py`
- Create: `host/tests/test_display_filter.py`

- [ ] **Step 1: Write failing initialization and update tests**

```python
import numpy as np

from sensor_host.acquisition.display_filter import ThreeAxisKalmanFilter


def test_filter_initializes_each_axis_from_first_sample() -> None:
    filter_ = ThreeAxisKalmanFilter(process_variance=1e-6, measurement_variance=2.25e-4)
    result = filter_.process(np.asarray([[1.0, -2.0, 0.5]], dtype=np.float64))
    np.testing.assert_allclose(result, [[1.0, -2.0, 0.5]])


def test_filter_smooths_measurement_step_without_cross_axis_coupling() -> None:
    filter_ = ThreeAxisKalmanFilter(process_variance=1e-6, measurement_variance=2.25e-4)
    samples = np.asarray([[0.0, 5.0, -3.0], [1.0, 5.0, -3.0]], dtype=np.float64)
    result = filter_.process(samples)
    assert 0.0 < result[1, 0] < 1.0
    np.testing.assert_allclose(result[:, 1], [5.0, 5.0])
    np.testing.assert_allclose(result[:, 2], [-3.0, -3.0])
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& .\build\host-package\.venv\Scripts\python.exe -m pytest .\host\tests\test_display_filter.py -q
```

Expected: collection fails because `sensor_host.acquisition.display_filter` does not exist.

- [ ] **Step 3: Implement the minimal filter**

```python
class ThreeAxisKalmanFilter:
    def __init__(self, process_variance: float, measurement_variance: float) -> None:
        if process_variance <= 0.0 or measurement_variance <= 0.0:
            raise ValueError("Kalman variances must be positive")
        self._q = process_variance
        self._r = measurement_variance
        self.reset()

    def reset(self) -> None:
        self._estimate: NDArray[np.float64] | None = None
        self._covariance = np.full(3, self._r, dtype=np.float64)

    def process(self, samples: NDArray[np.float64]) -> NDArray[np.float64]:
        values = np.asarray(samples, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != 3:
            raise ValueError("samples must have shape (n, 3)")
        output = np.empty_like(values)
        for index, measurement in enumerate(values):
            if self._estimate is None:
                self._estimate = measurement.copy()
            else:
                predicted_covariance = self._covariance + self._q
                gain = predicted_covariance / (predicted_covariance + self._r)
                self._estimate += gain * (measurement - self._estimate)
                self._covariance = (1.0 - gain) * predicted_covariance
            output[index] = self._estimate
        return output
```

- [ ] **Step 4: Add reset, validation and deterministic chunk-continuity tests**

Test that processing two consecutive chunks equals processing their concatenation, `reset()` makes the next sample a fresh estimate, empty `(0, 3)` input is accepted, and non-positive variances or invalid shapes raise `ValueError`.

- [ ] **Step 5: Run tests and commit**

```powershell
& .\build\host-package\.venv\Scripts\python.exe -m pytest .\host\tests\test_display_filter.py -q
git add host/src/sensor_host/acquisition/display_filter.py host/tests/test_display_filter.py
git commit -m "feat(host): add three-axis display Kalman filter"
```

Expected: all display-filter tests pass.

### Task 2: Preserve parallel raw and filtered sample retention

**Files:**
- Modify: `host/src/sensor_host/acquisition/sample_store.py`
- Modify: `host/tests/test_sample_store.py`

- [ ] **Step 1: Write failing raw/filtered snapshot tests**

Add tests constructing a noisy constant signal, calling `append_iis()`, and asserting:

```python
raw = store.snapshot(window_s=1.0, max_points=5000, use_kalman=False)
filtered = store.snapshot(window_s=1.0, max_points=5000, use_kalman=True)
assert np.std(filtered.x_g) < np.std(raw.x_g)
np.testing.assert_allclose(filtered.time_s, raw.time_s)
```

Also assert that default `snapshot()` output is byte-for-byte equivalent to the existing raw behavior.

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
& .\build\host-package\.venv\Scripts\python.exe -m pytest .\host\tests\test_sample_store.py -q
```

Expected: failure because `snapshot()` does not accept `use_kalman` and chunks do not contain filtered values.

- [ ] **Step 3: Extend `_SampleChunk` and append processing**

Add `filtered_acceleration_g` to `_SampleChunk`. Construct one `ThreeAxisKalmanFilter(1e-6, 2.25e-4)` in `RealtimeSampleStore.__init__`, process each newly appended IIS batch once, and store raw and filtered arrays in the same bounded chunk.

- [ ] **Step 4: Select the requested series before envelope extraction**

Change `snapshot(window_s, max_points, use_kalman=False)` so `_window_arrays_locked()` returns timestamps plus raw and filtered acceleration. Select one series before calling `envelope_indices()`; do not filter the already peak-selected 5,000 points.

- [ ] **Step 5: Preserve pruning and reset behavior**

Slice both raw and filtered arrays when pruning the first chunk. Reset the filter on store construction and before accepting a batch whose first timestamp is not greater than the last retained timestamp.

- [ ] **Step 6: Run tests and commit**

```powershell
& .\build\host-package\.venv\Scripts\python.exe -m pytest .\host\tests\test_sample_store.py .\host\tests\test_display_filter.py -q
git add host/src/sensor_host/acquisition/sample_store.py host/tests/test_sample_store.py
git commit -m "feat(host): retain filtered display samples"
```

Expected: raw snapshots remain unchanged and filtered snapshots pass smoothing, timestamp and retention assertions.

### Task 3: Wire the display preference through the controller

**Files:**
- Modify: `host/src/sensor_host/presentation/app_controller.py`
- Modify: `host/src/sensor_host/presentation/main_window.py`
- Modify: `host/src/sensor_host/app.py`
- Modify: `host/tests/test_app_controller.py`
- Modify: `host/tests/test_widgets.py`

- [ ] **Step 1: Write failing preference and signal tests**

Assert that `ApplicationController` starts with filtering disabled, `set_kalman_enabled(True)` causes the next `store.snapshot()` call to receive `use_kalman=True`, and `MainWindow.kalman_toggled` emits the checked state of the header button.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
& .\build\host-package\.venv\Scripts\python.exe -m pytest .\host\tests\test_app_controller.py .\host\tests\test_widgets.py -q
```

Expected: failures because the preference, signal and button do not exist.

- [ ] **Step 3: Add the header control and relay signal**

Create `self.kalman_button = QPushButton("KALMAN")` beside Auto Y, make it checkable and unchecked, and connect it to a new `MainWindow.kalman_toggled = pyqtSignal(bool)` signal. Keep the button inside `VibrationView.header_actions`.

- [ ] **Step 4: Add controller state and application wiring**

Add `_kalman_enabled = False`, a `set_kalman_enabled(bool)` slot, and pass the value into `store.snapshot(..., use_kalman=self._kalman_enabled)`. Connect `window.kalman_toggled` to the controller in `app.py`. Reset the preference to false during session clearing and update the button state without re-emitting during disconnect.

- [ ] **Step 5: Run tests and commit**

```powershell
& .\build\host-package\.venv\Scripts\python.exe -m pytest .\host\tests\test_app_controller.py .\host\tests\test_widgets.py -q
git add host/src/sensor_host/presentation/app_controller.py host/src/sensor_host/presentation/main_window.py host/src/sensor_host/presentation/vibration_view.py host/src/sensor_host/app.py host/tests/test_app_controller.py host/tests/test_widgets.py
git commit -m "feat(host): toggle Kalman display mode"
```

Expected: controller and widget tests pass with raw display remaining the default.

### Task 4: Correct typography, action transparency and orientation status

**Files:**
- Modify: `host/src/sensor_host/presentation/main_window.py`
- Modify: `host/src/sensor_host/presentation/orientation_view.py`
- Modify: `host/src/sensor_host/presentation/theme.py`
- Modify: `host/tests/test_widgets.py`

- [ ] **Step 1: Write failing role and hierarchy tests**

Assert that brand/model labels use dedicated `brand` and `sensor-id` roles, their minimum height is 32 px, `card-actions` is transparent in the stylesheet, and orientation mode/freshness labels are children of a transparent `orientation-overlay` stacked above the canvas rather than members of a separate status row.

- [ ] **Step 2: Run widget tests and verify RED**

```powershell
& .\build\host-package\.venv\Scripts\python.exe -m pytest .\host\tests\test_widgets.py -q
```

Expected: failures for missing roles and overlay hierarchy.

- [ ] **Step 3: Apply typography roles**

Use 12 px UI sans-serif text, 600-650 weight, explicit 32 px minimum height and restrained letter spacing for the brand and sensor identifier. Retain cyan color but remove their dependence on the generic monospace eyebrow role.

- [ ] **Step 4: Build the orientation overlay**

Place the OpenGL/fallback canvas and a mouse-transparent overlay widget in a `QStackedLayout` with `StackAll`. Align two compact pill labels to top-right; keep the remainder of the overlay transparent and ensure mode/freshness updates reuse the existing labels.

- [ ] **Step 5: Run tests and commit**

```powershell
& .\build\host-package\.venv\Scripts\python.exe -m pytest .\host\tests\test_widgets.py -q
git add host/src/sensor_host/presentation/main_window.py host/src/sensor_host/presentation/orientation_view.py host/src/sensor_host/presentation/theme.py host/tests/test_widgets.py
git commit -m "refactor(host): align header and orientation status"
```

Expected: widget hierarchy, role and existing orientation fallback tests pass.

### Task 5: Apply approved soft metric tiles and semantic health colors

**Files:**
- Modify: `host/src/sensor_host/presentation/main_window.py`
- Modify: `host/src/sensor_host/presentation/orientation_view.py`
- Modify: `host/src/sensor_host/presentation/theme.py`
- Modify: `host/tests/test_widgets.py`

- [ ] **Step 1: Write failing tile and health-state tests**

Assert all attitude/health fields have `role="metric-tile"`; the stylesheet specifies `#1C2D42`, no tile border and 6 px radius; zero counters are neutral; nonzero CRC/sequence/CDC counters receive `warning`; nonzero source/transport drops receive `critical`; sample rate and uptime stay neutral.

- [ ] **Step 2: Run widget tests and verify RED**

```powershell
& .\build\host-package\.venv\Scripts\python.exe -m pytest .\host\tests\test_widgets.py -q
```

- [ ] **Step 3: Add tile roles and stylesheet**

Set `role="metric-tile"` on existing attitude and health field frames. Apply background `#1C2D42`, no border, 6 px radius, and the approved internal padding without changing the current two-column/four-column responsive behavior.

- [ ] **Step 4: Apply value-only semantic state**

During `MainWindow.update_snapshot()`, set and repolish a `severity` property on health value labels only. Map CRC, sequence-gap and CDC nonzero values to `warning`; source/transport drops to `critical`; all zero values plus sample rate/uptime to `normal`.

- [ ] **Step 5: Test large counters and commit**

Resize to 1080 x 700, inject counters above one million, and assert every label meets its size hint without changing the seven-column health layout.

```powershell
& .\build\host-package\.venv\Scripts\python.exe -m pytest .\host\tests\test_widgets.py -q
git add host/src/sensor_host/presentation/main_window.py host/src/sensor_host/presentation/orientation_view.py host/src/sensor_host/presentation/theme.py host/tests/test_widgets.py
git commit -m "style(host): add soft telemetry tiles"
```

### Task 6: Performance, full regression and visual baselines

**Files:**
- Modify: `host/tests/test_replay_performance.py`
- Modify: `host/tests/golden/visual/dark-live-monitor.png`

- [ ] **Step 1: Add a filtered ingestion performance assertion**

Replay at least two million IIS payload bytes through the store with filtered retention enabled. Assert processing remains faster than the represented sensor duration and snapshot output remains at or below 5,000 points.

- [ ] **Step 2: Run the complete source suite**

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& .\build\host-package\.venv\Scripts\python.exe -m pytest .\host\tests .\test\test_protocol.py -q
& .\build\host-package\.venv\Scripts\python.exe -m compileall -q .\host\src .\host\tools
```

Expected: all tests and compilation pass without warnings from project code.

- [ ] **Step 3: Regenerate the deterministic visual baseline**

```powershell
& .\build\host-package\.venv\Scripts\python.exe .\host\tools\capture_visual_baseline.py --output .\host\tests\golden\visual\dark-live-monitor.png
```

Inspect at 1920 x 1080 and produce a temporary 1080 x 700 capture. Confirm aligned brand/model text, transparent action area, readable status pills, soft tiles, large counters, and no clipping.

- [ ] **Step 4: Run the full single-file package gate**

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\package_host.ps1
```

Expected: source tests pass, PyInstaller produces `dist/host/STM32SensorHost-0.1.0-win64.exe`, the packaged smoke test exits zero, and the JSON manifest matches the executable SHA-256 and byte length.

- [ ] **Step 5: Run firmware regression and commit evidence**

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\test_stage1.ps1
git diff --check
git add host/tests/test_replay_performance.py host/tests/golden/visual/dark-live-monitor.png
git commit -m "test(host): verify filtered telemetry UI"
```

Expected: Stage 1 completes 8/8, including Debug and Release firmware builds.

### Task 7: Final review and merge handoff

**Files:**
- Review: all branch changes relative to `master`
- Artifact: `dist/host/STM32SensorHost-0.1.0-win64.exe`
- Manifest: `dist/host/STM32SensorHost-0.1.0-win64.json`

- [ ] **Step 1: Review branch scope and user-owned files**

```powershell
git status --short --branch
git diff --check master...HEAD
git diff --stat master...HEAD
git -C ..\.. status --short --branch
```

Confirm `.clangd` and `docs/JY61PL_iis3dwb/` remain untouched and excluded from commits.

- [ ] **Step 2: Provide executable and screenshots for user acceptance**

Report the commit list, test counts, Stage 1 result, executable byte length and SHA-256. Do not merge before the user accepts the real application appearance.

- [ ] **Step 3: Merge only after explicit approval**

Use the finishing-a-development-branch workflow, rerun the complete verification commands, merge `codex/host-ui-card-polish` into the user-designated mainline, and preserve unrelated working-tree changes.
