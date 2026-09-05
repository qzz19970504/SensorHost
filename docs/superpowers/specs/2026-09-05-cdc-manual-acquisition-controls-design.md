# CDC Manual Acquisition Controls Design

**Status:** Complete  
**Date:** 2026-09-05  
**Scope:** SensorHost desktop application only

## Problem statement

The Windows host can open the STM32 USB CDC endpoint and decode valid SDF1
control and sensor frames, but the normal GUI connection flow cannot start a
CDC live session. `CONNECT` currently opens the port and sends only read-only
UUID, state, and live-target queries. The firmware intentionally boots in
`IDLE` with `LIVESTREAM=UART`, so a connected host receives no sensor frames
until an operator changes the target to CDC and starts acquisition.

The application already implements the underlying `AT+START`, `AT+STOP`, and
`AT+LIVESTREAM=UART|CDC` controller methods. The defect is that the main GUI
does not expose them. Operators must discover and type protocol commands in the
console even though the README describes those actions as manual controls.

## Verified fault boundary

The following live checks were completed against COM6 before this design:

- Windows enumerated COM6 as `USB\\VID_0483&PID_5740`, status OK.
- CDC accepted `AT+STATE?` and `AT+LIVESTREAM?`; the host decoded two valid
  SDF1 control frames with zero CRC errors and zero discarded bytes.
- The device reported `STATE=IDLE` and `LIVESTREAM=UART`.
- After explicitly selecting CDC and issuing START, a three-second capture
  received 421,356 bytes: 121 IIS3DWB frames and one JY61PL frame, with zero
  CRC errors and zero discarded bytes.
- STOP succeeded, and the live target was restored to UART while IDLE.

These results prove that USB enumeration, firmware CDC receive/transmit,
firmware SDF1 framing, host serial reads, and host SDF1 parsing work. The
missing transition is confined to the desktop GUI workflow.

## User-facing design

Add three acquisition controls to the existing top acquisition toolbar:

1. A `LIVE TARGET` selector containing `UART` and `CDC`.
2. A `START` button that sends `AT+START` to the selected connected node.
3. A `STOP` button that sends `AT+STOP` to the selected connected node.

The controls are disabled while no node is connected and enabled while a CDC
session or Wi-Fi gateway session is active. They operate on the node selected
in the existing node sidebar, matching the current watermark, console, and
archive-command routing model.

Changing `LIVE TARGET` sends the corresponding live-target command only when a
node is connected. The selector defaults to `UART`, matching the firmware
cold-start default. When a structured firmware response reports the actual
target, the selector is updated without sending a command back to the device.
After an operator change, the host immediately requests authoritative target
state and briefly ignores older display snapshots so they cannot visually undo
an in-flight command. If the firmware rejects the change, normal synchronization
resumes and restores the reported target.

`CONNECT` remains a read-only connection action. It will not stop acquisition,
switch away from an ESP32/UART stream, start sensors, or restore a target on
disconnect. This preserves operator control and avoids surprising state changes
merely from attaching a debug host.

## Required operating sequence

For a normal cold boot on COM6:

1. Select COM6 and click `CONNECT`.
2. Confirm the node is selected.
3. Select `CDC` under `LIVE TARGET`.
4. Click `START`.

If acquisition is already active with UART selected, the firmware rejects a
target change with `ERROR:STATE`. The operator must click `STOP`, wait for the
`OK` response and IDLE state, select `CDC`, and then click `START`. The host
must show firmware replies in the existing console instead of hiding this
protocol constraint.

## Component changes

### Main window

`src/sensor_host/presentation/main_window.py` will own the new widgets and
signals. It will:

- emit start and stop requests;
- emit a live-target request only for an operator-initiated selector change;
- enable or disable the widgets as part of `set_connected()`;
- synchronize the selector from `UiSnapshot.firmware_control_state` while
  blocking widget signals to prevent a command echo loop.

### Application wiring

`src/sensor_host/app.py` will connect the new window signals to the existing
`AppController.start_acquisition()`, `stop_acquisition()`, and
`set_livestream()` entry points.

### Application controller

`src/sensor_host/presentation/app_controller.py` will expose selected-node
start and stop slots, with explicit-node helper methods following the existing
watermark and live-target routing pattern. Missing selections and unknown node
identifiers will produce actionable errors through `error_raised`.

The Qt-free `AcquisitionController` and CDC transport require no behavioral
change because their live hardware path has already passed.

## Error handling

- START, STOP, and target changes with no selected node report a clear console
  error.
- An unknown node identifier reports `unknown node: <id>`.
- Invalid targets continue to be rejected by `AcquisitionController`.
- Firmware responses such as `ERROR:STATE`, `ERROR:BUSY`, or `OK` remain visible
  in the console. The GUI does not claim success before the firmware responds.
- Transport failures continue through the existing worker failure and
  disconnect path.

## Verification strategy

Tests will be written before implementation and will cover:

- widget presence, default target, and disconnected/connected enable states;
- operator target changes emitting one request while snapshot synchronization
  emits none;
- START and STOP routing only to the selected node;
- missing-selection and unknown-node errors;
- application signal wiring through a behavioral Qt smoke test;
- the existing complete host test suite and compile checks;
- a live COM6 check using the new GUI/controller path, ending in STOP and
  restoring UART/IDLE;
- visual inspection of the toolbar at the supported minimum window size.

## Documentation deliverable

Create `docs/USER_MANUAL_zh-CN.md` as the Chinese operator manual. It will
include installation and launch, COM6 identification, the exact cold-start and
UART-to-CDC transition sequences, live monitoring, recording, diagnostics,
archive export, shutdown, data paths, and symptom-based troubleshooting. The
root README will link to the manual and describe the newly exposed controls.

## Non-goals

- No STM32 source, configuration, build artifact, flash contents, or persistent
  firmware setting will be modified.
- No automatic STOP, START, target switching, or reconnect state machine will
  be introduced.
- No CDC protocol, SDF1 format, Wi-Fi transport, recording format, or archive
  behavior will change.
