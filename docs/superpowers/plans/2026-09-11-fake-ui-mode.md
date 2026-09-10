# Fake UI Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a packaged `--fake` mode that drives the real SensorHost UI through a deterministic virtual SDF1 device.

**Architecture:** Implement one transport adapter under `sensor_host.transport` that owns only virtual-device state and valid SDF1 encoding. Reuse the existing application composition and controller wiring, selecting the adapter through the app entry point and auto-connecting its descriptor. Keep fake behavior deterministic, bounded, and independent of presentation code.

**Tech Stack:** Python 3.11+, PyQt6, existing SDF1 `StreamParser`, pytest/pytest-qt, PyInstaller.

---

### Task 1: Virtual transport contract

**Files:**
- Create: `src/sensor_host/transport/fake.py`
- Modify: `src/sensor_host/transport/__init__.py`
- Test: `tests/test_fake_transport.py`

- [ ] **Step 1: Write failing tests** for one fake descriptor, valid UUID/state responses, valid live sample frames, command state transitions, slow archive frames, Cancel, and confirmed SD clear.
- [ ] **Step 2: Run `pytest tests/test_fake_transport.py -q` and verify the missing adapter/import fails.**
- [ ] **Step 3: Implement `FakeTransport` with bounded read-time scheduling, valid SDF1 v1/v2 frames, deterministic JY/IIS data, and command handling.
- [ ] **Step 4: Run the focused fake transport tests and verify they pass.**

### Task 2: Application launch mode

**Files:**
- Modify: `src/sensor_host/app.py`
- Test: `tests/test_packaging.py`

- [ ] **Step 1: Add a failing test that `main(["stm32-sensor-host", "--fake", "--smoke-test"])` is accepted and that fake descriptors are available without serial discovery.**
- [ ] **Step 2: Run the focused tests and verify the flag is currently unsupported.**
- [ ] **Step 3: Share the existing interactive wiring while substituting `FakeTransport`, populating `FAKE-001`, and auto-connecting it; retain smoke-test precedence.**
- [ ] **Step 4: Run packaging/launch tests and verify they pass.**

### Task 3: Operator documentation and regression

**Files:**
- Modify: `README.md`
- Test: `tests/test_app_smoke.py` or `tests/test_fake_transport.py`

- [ ] **Step 1: Add a failing assertion for the documented `--fake` invocation.**
- [ ] **Step 2: Run it and verify the documentation is absent.**
- [ ] **Step 3: Add the concise fake-mode usage section and an end-to-end controller test proving real acquisition receives synthetic frames.**
- [ ] **Step 4: Run the complete source suite and compile check.**

### Task 4: Commit and package

**Files:**
- Commit only the fake-mode source, tests, docs, and design/plan records.

- [ ] **Step 1: Review the diff and verify no firmware path is staged.**
- [ ] **Step 2: Commit with `feat(host): add fake UI transport mode`.**
- [ ] **Step 3: Reuse `D:\Codes\SensorHost\build\host-package\.venv`, build the one-file executable, and run its smoke test.**
- [ ] **Step 4: Record the executable path, byte length, and SHA-256 manifest for user verification.**
