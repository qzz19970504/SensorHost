# STM32 SD-Staged OTA Acceptance — SensorHost

Date: 2026-09-17
Branch: `feat/host-ota-upload`
Status: **PENDING HARDWARE** — the host-side OTA feature is implemented and
unit/integration tested (see `tests/test_ota_*.py`, all green). The physical
negative/positive acceptance below requires an STM32F407 target on USART2 (via
an ESP32 UART bridge or a bench split-serial pair) and has not been run in this
environment.

## Scope

Verifies the host OTA entry and uploader against the firmware contract without
modifying firmware:

1. Negative: a tampered image (valid per-frame CRCs, wrong image CRC) must be
   rejected at COMMIT with `+OTA:NACK,CODE=IMAGE_CRC`, and the session must stay
   `RECEIVING`; `CANCEL` then closes it.
2. Positive: a clean package streams with per-frame `+OTA:ACK`, COMMIT yields
   `+OTA:STAGED,VERSION=a.b.c,CRC=%08X` whose CRC matches the local package, the
   device resets, and after reconnect `AT+STATE?` reports `+OTA:STATE=OFF` with
   the live stream resumed.

## Prerequisites

- A built `app.ota` from the firmware repo (e.g. `build/Debug/app.ota`), target
  ID `F407VE-JY-I3DWB`, manifest state `PACKAGE`.
- Device SD `READY=1` and `FORMAT_REQUIRED=0`.
- Link: ESP32 UART bridge (Wi-Fi) or bench USART2 + CDC split.

## Run — ESP32 UART bridge (production path)

```powershell
python tools/ota_acceptance.py `
    --input <firmware>/build/Debug/app.ota `
    --tcp-listen 54321 --wake-udp 192.168.137.255:12345 `
    --state-port COM19 `
    --baud 460800 --report docs/validation/ota-2026-09-17/acceptance.json
```

## Run — bench split serial

```powershell
python tools/ota_acceptance.py `
    --input <firmware>/build/Debug/app.ota `
    --command-port COM12 --response-port COM19 --baud 460800 `
    --report docs/validation/ota-2026-09-17/acceptance.json
```

## Cross-check

The same package can be validated against the firmware repo's own gate:

```powershell
python <firmware>/tools/ota_bench_gate.py --command-port COM12 --response-port COM19 `
    --baud 460800 --input <firmware>/build/Debug/app.ota
```

## Evidence (fill in after a hardware run)

| Check | Expected | Observed | Pass |
|---|---|---|---|
| Tampered COMMIT reply | `+OTA:NACK,CODE=IMAGE_CRC,...` | _pending_ | ☐ |
| State after tampered COMMIT | `+OTA:STATE=RECEIVING` | _pending_ | ☐ |
| CANCEL after tamper | `+OTA:ACK`, then `+OTA:STATE=OFF` | _pending_ | ☐ |
| Clean stream | per-frame `+OTA:ACK` advancing `NEXT` | _pending_ | ☐ |
| Clean COMMIT | `+OTA:STAGED,VERSION,CRC` + `OK` | _pending_ | ☐ |
| STAGED CRC vs package | equal | _pending_ | ☐ |
| After reset + reconnect | `+OTA:STATE=OFF`, live resumed | _pending_ | ☐ |

Attach `acceptance.json` (written by `--report`) alongside this file.

## Host UI manual check

1. Connect a Wi-Fi gateway node; the toolbar **FIRMWARE** button becomes enabled.
2. Connect a CDC node instead; **FIRMWARE** is greyed out with tooltip
   "OTA 仅支持 UART 来源链路（Wi-Fi 网关）".
3. Open **FIRMWARE**, select a `.ota`, confirm the summary (target/version/size/CRC).
4. Start the upload; watch the progress bar and phase text; the DIAGNOSTICS page
   shows `OTA STATE/RECEIVED/TOTAL/ERROR`.
5. On `+OTA:STAGED` the dialog shows the device VERSION/CRC and whether it matches
   the local package, then "等待设备重启"; the host auto-reconnects (Wi-Fi or CDC)
   and reports RECONNECTED. The expected reset disconnect is not shown as an error.
