# Host UI Readability Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve font hierarchy and spatial balance in the existing PyQt sensor dashboard without changing runtime behavior.

**Architecture:** Keep the existing presentation components and signals. Add semantic label roles and explicit initial splitter sizes so QSS owns typography while the window owns layout; stream-health data remains updated by `MainWindow.update_snapshot()` through named value labels.

**Tech Stack:** Python 3.12, PyQt6, pytest-qt, pyqtgraph, Qt offscreen rendering

---

### Task 1: Lock the readable metric layout

**Files:**
- Modify: `host/tests/test_widgets.py`

- [x] **Step 1: Write failing layout tests**

Add assertions that `AttitudeView` uses two grid columns and that every value
label has `role="metric"`. Add a `MainWindow` assertion for seven named health
value labels and initial main/right splitter proportions.

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe -m pytest host/tests/test_widgets.py -q
```

Expected: failures for the current four-column grid, absent metric role, absent
health labels, and unexposed splitter sizes.

### Task 2: Implement typography and layout hierarchy

**Files:**
- Modify: `host/src/sensor_host/presentation/theme.py`
- Modify: `host/src/sensor_host/presentation/main_window.py`
- Modify: `host/src/sensor_host/presentation/orientation_view.py`

- [x] **Step 1: Apply semantic typography**

Set the base font to 13 px, eyebrow labels to 12 px, and metric labels to 16 px
bold Consolas. Increase buttons and inputs to 32 px minimum height.

- [x] **Step 2: Balance the live dashboard**

Expose `main_splitter` and `right_splitter`, initialize them near 70:30 and
56:44, use a two-column attitude grid, and replace `health_summary` with seven
equal-width metric cells stored in `health_value_labels`.

- [x] **Step 3: Run focused tests and verify GREEN**

Run the Task 1 command. Expected: all selected tests pass.

- [x] **Step 4: Run the complete host suite**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe -m pytest host/tests -q
```

Expected: all tests pass.

### Task 3: Visual and real-device verification

**Files:**
- Modify: `host/tests/golden/visual/dark-live-monitor.png`

- [x] **Step 1: Regenerate the deterministic baseline**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe .\host\tools\capture_visual_baseline.py --output .\host\tests\golden\visual\dark-live-monitor.png
```

Expected: PNG generation succeeds at 1920x1080.

- [x] **Step 2: Inspect the baseline and real 1440x900 UI**

Verify non-overlapping controls, readable metric hierarchy, balanced panes,
live XYZ updates, orientation rendering, health status, and disconnect behavior.

- [x] **Step 3: Commit the polish**

```powershell
git add host/src/sensor_host/presentation host/tests/test_widgets.py host/tests/golden/visual/dark-live-monitor.png docs/superpowers/plans/2026-08-28-host-ui-polish.md
git commit -m "style: improve host dashboard readability"
```
