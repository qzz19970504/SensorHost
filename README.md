# SensorHost

Independent Windows desktop application for SDF1 vibration and orientation acquisition.
Connect one STM32 over USB CDC, or accept up to 16 ESP32 transparent TCP bridges.
Each node has independent parsing, diagnostics, selected-node commands and recording.

Chinese operator guide: [上位机操作手册](docs/USER_MANUAL_zh-CN.md).

## Develop

Run from this repository root. Python 3.11 or newer is required.

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e '.[dev]'
& .\.venv\Scripts\stm32-sensor-host.exe
```

No STM32 or ESP32 source checkout, compiler, sibling directory or submodule is required.

## Test and package

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\.venv\Scripts\python.exe -m pytest tests -q
& .\.venv\Scripts\python.exe -m compileall -q src tools
git diff --check
powershell -ExecutionPolicy Bypass -File .\tools\package_host.ps1
```

The packager creates an isolated environment, runs the source tests, builds a one-file
Windows EXE, runs its smoke test and writes a SHA-256 manifest under `dist/host/`.
See [build environment](docs/HOST_BUILD_ENVIRONMENT.md).

## Connect and record

Choose CDC for one serial device, or WI-FI for a TCP listener. In Wi-Fi mode select
the hotspot IPv4 interface and enter the PC IPv4 configured in the ESP firmware.
They must match. Defaults are TCP 54321 and UDP 12345. The PC sends `TCPCONNECT`
every two seconds to the subnet broadcast plus optional ESP unicast addresses.
PC and ESP devices must share a hotspot permitting client communication; allow
inbound TCP through Windows Firewall when prompted or configure it manually.

Select a device in DEVICES to view its data and send commands. Automatic commands
are read-only UUID, STATE and LIVESTREAM queries. Use the toolbar's LIVE TARGET,
START and STOP controls for manual acquisition: on a cold boot, connect COM6, select
CDC, then click START. If UART acquisition is already active, click STOP, wait for
OK/IDLE, select CDC, then click START. RECORD starts separate per-node files and includes later arrivals.
Reconnects create new segments. Archive exports are saved separately from live data.
The 30-second plot window does not limit recording duration.

Data defaults to `%LOCALAPPDATA%\SensorHost` on Windows:

```text
SensorHost/
  recordings/<batch>/<alias>-<uuid8>/segment-001.sdf1
  recordings/<batch>/<alias>-<uuid8>/segment-001.json
  exports/<batch>/<alias>-<uuid8>/export-001.sdf1
```

Set `SENSOR_HOST_DATA_DIR` to an absolute directory to override this location.
Example: `$env:SENSOR_HOST_DATA_DIR='D:\SensorData'`. Existing recordings are not moved.
Aliases and Wi-Fi settings retain the existing QSettings identity.

## Repository boundaries

- `src/sensor_host/`: application, SDF1 decoder, transports and storage.
- `tests/`: host tests, protocol golden vectors and visual fixtures.
- `tools/`: package, screenshot and manually invoked hardware acceptance tools.
- `docs/PROTOCOL.md`: imported wire-contract snapshot.
- [migration and compatibility](docs/MIGRATION.md): provenance, ownership and releases.

Historical design documents retain their original paths and describe their original
monorepo context. The `legacy-*` documents are reference only; use this README for
current commands. Soft-metrics/Kalman documents are plans, not implemented features.
