# Standalone repository provenance and compatibility

Extracted on 2026-09-05 from STM32407ZG_JY61PL_II3DWB_UART_V2.

- Firmware baseline: `1124a2df7ebaa9f9be976737cefacfb764b23d8a`.
- Wi-Fi implementation: original commit `12c0a7f`.
- UI improvements and future design documents: original tip `599733e`.
- Integration before filtering: original commit `445b460`.

Both feature histories were merged in an independent clone, then relevant paths
were extracted with git-filter-repo. Commit hashes change during extraction;
authors, messages and relevant parent history are retained. Original firmware
history and worktrees remain available in the source repository. There is no
remote back to the firmware repository and no shared Git object directory.

## Ownership

SensorHost owns the Python decoder, host tests, golden vectors, UI and EXE release.
Firmware owns embedded sources, C tests and a frozen Python reference decoder for
its protocol checks. That reference is a test oracle, not a second evolving desktop
application. Update the reference explicitly only when the firmware wire contract
changes. Run common golden-vector checks when coordinating a protocol release.

`docs/PROTOCOL.md` is the baseline contract snapshot. SDF1 V1/V2 and current AT
responses are supported; ESP32 remains a transparent bridge with no new framing.
No protocol or embedded implementation changes were made during extraction.

## Release discipline

Host versions are independent of firmware versions. Each host release should name
the supported firmware revision/protocol snapshot, source commit and EXE SHA-256.
Actual compatibility with future firmware requires contract tests and hardware
acceptance, not just matching application version numbers.

Clone this repository alone and run README checks to validate independence.
Soft metrics/Kalman are retained design work only. Existing recorded data and
untracked development environments remain at their previous locations.
