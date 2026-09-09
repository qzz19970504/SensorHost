# Independent host build

Run `powershell -ExecutionPolicy Bypass -File .\tools\package_host.ps1` from the root.
Use `-Python C:\path\to\python.exe` for an explicit Python interpreter. Otherwise
the script tries the existing local cached runtime, Windows Python launcher, then PATH.
Python 3.11+ is required. Network access may be needed to install dependencies.

The script uses `build/host-package/.venv`, tests only this repository, and builds
`STM32SensorHost.spec` at the root. PyInstaller is pinned in `requirements-build.txt`.
Qt/OpenGL optional-module warnings may occur; successful exit requires the packaged
EXE smoke test. No embedded build is invoked.

Output is `dist/host/VibrationSensorHost-<version>-win64.exe` and its JSON size/SHA-256
manifest. Bump `pyproject.toml` for a new release. Validate CDC and ESP hardware on
release candidates; offscreen tests do not establish real Wi-Fi/hardware behavior.
