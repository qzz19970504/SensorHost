# CDC Manual Acquisition Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose safe, explicit live-target, START, and STOP controls in SensorHost and document the complete COM6 operating workflow.

**Architecture:** Keep serial transport and protocol decoding unchanged because the live COM6 path already passed. Add presentation signals and selected-node controller slots, synchronize the target selector from structured firmware state without command feedback, and wire the new controls at the composition root.

**Tech Stack:** Python 3.12, PyQt6, pytest, pytest-qt, pyserial, Markdown

---

### Task 1: Add selected-node acquisition command routing

**Files:**
- Modify: `src/sensor_host/presentation/app_controller.py`
- Test: `tests/test_app_smoke.py`

- [ ] **Step 1: Write failing selected-node routing tests**

Add tests that connect a fake transport, wait for the three initial queries, call
`start_acquisition()` and `stop_acquisition()`, and assert that only the selected
transport receives `AT+START` and `AT+STOP`. Add a no-selection test asserting the
errors `select a connected node before starting acquisition` and
`select a connected node before stopping acquisition`.

```python
def test_selected_node_receives_start_and_stop_commands(qtbot) -> None:
    transport = RecordingIdleTransport()
    controller = AppController(lambda: transport)
    controller.connect_device("FAKE")
    try:
        qtbot.waitUntil(lambda: len(transport.commands) >= 3, timeout=1000)
        controller.start_acquisition()
        controller.stop_acquisition()
        qtbot.waitUntil(lambda: len(transport.commands) >= 5, timeout=1000)
        assert transport.commands[-2:] == [b"AT+START", b"AT+STOP"]
    finally:
        controller.disconnect_device()
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\.venv\Scripts\python.exe -m pytest tests\test_app_smoke.py -q
```

Expected: failure because `AppController` does not expose selected-node start and
stop methods.

- [ ] **Step 3: Implement selected-node start and stop slots**

Add `start_acquisition()`, `start_acquisition_for(node_id)`,
`stop_acquisition()`, and `stop_acquisition_for(node_id)` beside the existing
watermark and live-target methods. Selected-node entry points emit actionable
errors when no node is selected; explicit-node helpers emit `unknown node` when
the identifier is absent and otherwise delegate to the Qt-free acquisition
controller.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 1 command again. Expected: all `test_app_smoke.py` tests pass.

### Task 2: Add and synchronize toolbar controls

**Files:**
- Modify: `src/sensor_host/presentation/main_window.py`
- Test: `tests/test_widgets.py`

- [ ] **Step 1: Write failing widget tests**

Cover these behaviors independently:

- disconnected START, STOP, and target controls are disabled;
- connected controls are enabled and target defaults to UART;
- clicking START and STOP emits their corresponding signals once;
- an operator target change emits `CDC` once;
- a snapshot reporting CDC updates the selector without emitting an operator
  request.

Use `FirmwareControlState(livestream_target="CDC")` with `dataclasses.replace`
to build the synchronization snapshot.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\.venv\Scripts\python.exe -m pytest tests\test_widgets.py -q
```

Expected: failure because the new widgets and signals do not exist.

- [ ] **Step 3: Implement the toolbar controls**

In `MainWindow`:

- declare `start_requested`, `stop_requested`, and `livestream_requested`;
- create `live_target_combo` with `UART` and `CDC` entries;
- create `start_button` and `stop_button`;
- connect button clicks and `currentTextChanged` to the public signals;
- update their enabled states in `set_connected()`;
- in `update_snapshot()`, use `QSignalBlocker` while applying a reported UART or
  CDC target so state reflection never sends a command back to the device.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 2 command again. Expected: all `test_widgets.py` tests pass.

### Task 3: Wire the controls through the application

**Files:**
- Modify: `src/sensor_host/app.py`
- Test: `tests/test_app_smoke.py`

- [ ] **Step 1: Write a failing integration test**

Extract `_wire_acquisition_controls(window, controller)` as the narrow
composition helper. Test it with a real `MainWindow`, `AppController`, and fake
transport: connect the fake node, click START, click STOP, change the target to
CDC, then assert the fake transport receives the three matching commands.

- [ ] **Step 2: Run the integration test and verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\.venv\Scripts\python.exe -m pytest tests\test_app_smoke.py -q
```

Expected: failure because `_wire_acquisition_controls` does not exist.

- [ ] **Step 3: Implement composition wiring**

Add the helper to connect:

```python
window.start_requested.connect(controller.start_acquisition)
window.stop_requested.connect(controller.stop_acquisition)
window.livestream_requested.connect(controller.set_livestream)
```

Call it once from `_run_interactive()`.

- [ ] **Step 4: Run the integration test and verify GREEN**

Run the Task 3 command again. Expected: all `test_app_smoke.py` tests pass.

### Task 4: Create the Chinese operator manual and update the README

**Files:**
- Create: `docs/USER_MANUAL_zh-CN.md`
- Modify: `README.md`

- [ ] **Step 1: Write the manual**

Document prerequisites, installation, launching from source and packaged EXE,
COM6 identification by STM32 VID/PID, control meanings, cold-start operation,
UART-to-CDC transition, monitoring, recording, diagnostics, archive export,
safe shutdown, file locations, and symptom-based troubleshooting. State that
CDC baud rate is a placeholder and that firmware target changes are IDLE-only.

- [ ] **Step 2: Update README usage**

Link the Chinese manual near Quick Start and replace the obsolete statement that
START, STOP, and target changes lack GUI access with the exact toolbar workflow.

- [ ] **Step 3: Validate documentation**

Run:

```powershell
rg -n "COM6|VID_0483|LIVE TARGET|START|STOP|ERROR:STATE|USER_MANUAL_zh-CN" README.md docs\USER_MANUAL_zh-CN.md
git diff --check
```

Expected: every required operating concept is found and whitespace validation
passes.

### Task 5: Verify automated and live behavior

**Files:**
- No production changes expected

- [ ] **Step 1: Run complete automated verification**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\.venv\Scripts\python.exe -m pytest tests -q
& .\.venv\Scripts\python.exe -m compileall -q src tools
& .\.venv\Scripts\stm32-sensor-host.exe --smoke-test
git diff --check
```

Expected: every command exits 0 with no failed tests.

- [ ] **Step 2: Inspect the rendered toolbar**

Capture the offscreen window at 1080x700 and inspect that LIVE TARGET, START,
and STOP remain visible, legible, and do not overlap neighboring controls.

- [ ] **Step 3: Run COM6 controller-path acceptance**

Use `CdcSerialTransport`, `AppController`, and the new public methods—not direct
raw commands—to connect COM6, select CDC, start, observe non-zero decoded sensor
frames with zero CRC errors, stop, wait for IDLE, restore UART, and disconnect.
If COM6 is absent or busy, report the hardware gate as unverified instead of
claiming it passed.

- [ ] **Step 4: Audit repository boundaries**

Run:

```powershell
git -C D:\Codes\SensorHost status --short
git -C D:\Codes\STM32\STM32407ZG_JY61PL_II3DWB_UART_V2 status --short
```

Expected: only planned SensorHost files changed; the firmware repository retains
only its pre-existing `.clangd` modification.
