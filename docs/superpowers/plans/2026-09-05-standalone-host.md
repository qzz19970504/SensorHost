# Standalone SensorHost migration

Goal: independently clone, test, build and run the desktop host without either embedded repository.

Architecture: retain the sensor_host Python package, TCP/CDC transports and presentation modules. Move host-owned protocol fixtures, packaging and documentation into the new repository. Preserve embedded firmware source and its independent protocol checks.

- [x] Clone source history into D:/Codes/SensorHost without shared Git objects.
- [x] Integrate Wi-Fi commit 12c0a7f and UI branch 599733e; resolve presentation conflicts retaining both features.
- [ ] Extract relevant history and promote host contents to repository root.
- [ ] Bring protocol golden fixtures and tests into tests; retain firmware source inspection tests in the firmware repository.
- [ ] Update imports, packaging paths, recording locations and user documentation for standalone use.
- [ ] Run standalone pytest, compileall, diff checks, full EXE packaging and a clean-clone check.
- [ ] Remove the old tracked host application only after verifying the new repository; preserve firmware protocol test independence and add migration documentation.
- [ ] Verify embedded source unchanged, existing user edits preserved, and both Git repositories independently usable.

Compatibility: document the source firmware revision, SDF1 contract snapshot and ESP bridge assumptions. Keep unfinished Kalman/metrics specifications as future work; do not implement them as part of extraction.
