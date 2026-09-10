# Fake UI Mode Design

## Goal

Add a `--fake` launch mode that lets operators exercise the existing SensorHost
UI without a connected STM32 or any firmware process.

## Scope and decisions

- `--fake` starts the normal interactive main window with one automatically
  connected virtual node.
- The virtual node uses the existing `Transport` contract and feeds valid SDF1
  frames through the normal `AcquisitionController`, parser, store, and
  presentation layers. No presentation-only shortcuts or test-only UI paths
  are added.
- The virtual node starts in `IDLE`, emits deterministic synthetic IIS3DWB and
  JY61PL samples for plot/orientation coverage, and reports a populated SD
  ring so the SD Archive tab is immediately useful.
- It accepts the host's existing control commands: UUID/state/live queries,
  START/STOP, live-target changes, EXPORT, export cancellation through STOP,
  and `AT+SDCLEAR=CONFIRM`. EXPORT emits archive-flagged SDF1 frames slowly
  enough to exercise progress and Cancel. Clear remains destructive only after
  the existing UI confirmation and host/firmware state gate.
- `--smoke-test` keeps its current precedence and does not enter the event loop;
  combining it with `--fake` remains a deterministic packaging smoke test.
- The real CDC and gateway transports, firmware repository, and wire protocol
  are unchanged.

## Components and data flow

1. `sensor_host.transport.fake.FakeTransport` owns virtual device state,
   command responses, sample scheduling, archive scheduling, and SDF1 frame
   encoding. It exposes one `FAKE-001` descriptor.
2. `sensor_host.app` recognizes `--fake`, uses `FakeTransport` as the factory,
   populates the device selector from its descriptor, and connects that node
   automatically. All other signal wiring is shared with the real interactive
   path.
3. Tests exercise the transport through `StreamParser`/`AcquisitionController`
   and verify the application accepts the flag. A short README section records
   the operator command.

## Error handling

- Reads before `open` and unknown device IDs raise the same transport-level
  errors expected by the real adapters.
- Invalid or unavailable commands return CLI `ERROR:STATE`/`ERROR:UNKNOWN`
  frames rather than mutating virtual state.
- Fake timing is monotonic and bounded by the caller's read timeout; it must
  not create an unbounded producer queue or background thread.

## Acceptance criteria

- `stm32-sensor-host --fake` opens the normal dashboard without serial hardware.
- The live monitor receives both vibration and orientation data.
- SD Archive shows a populated virtual record; EXPORT produces visible progress;
  Cancel returns to idle; CLEAR SD can be confirmed and sends the real command.
- Existing source tests remain green, the fake-specific tests pass, and the
  packaged executable accepts `--fake` without importing a serial device.
