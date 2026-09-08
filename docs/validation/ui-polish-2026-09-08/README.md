# UI polish hardware validation — 2026-09-08

Device: STM32 CDC COM6, USB 0483:5740. Baseline: aeacedf.

- Real CDC through MainWindow/AppController: Connect, live curve, RECORD,
  paused CLEAR, continued acquisition/recording, resume, STOP, restore UART,
  Disconnect and immediate reconnect passed. Final device state: IDLE / UART.
- Rapid reconnect exposed a pre-existing queued-callback race: an old session
  could dispose the new session using the same port. Session identity guards and
  a regression test now protect both failure and thread-finished callbacks.
- The full no-drop CDC acceptance is NOT passing on this hardware/firmware.
  Current code, 30.219 s: 590 frames, 0 CRC errors, 13 sequence gaps,
  source drop +3544; recorded and replayed frame counts match.
  Unmodified baseline, 15.141 s: 304 frames, 0 CRC errors, 4 sequence gaps,
  source drop +1920. Both restored UART successfully.
  Firmware diagnostics also report POOL_FAIL, POOL_MIN=0 and SD_STALL_MS=65.
  This reproduces before the UI change; the firmware/source bottleneck remains
  unresolved and is not a successful lossless-stream acceptance.
- TCP inactivity/capacity behavior is verified with local socket regression tests,
  not a physical Wi-Fi bridge in this run.

See the adjacent JSON files for raw evidence.
