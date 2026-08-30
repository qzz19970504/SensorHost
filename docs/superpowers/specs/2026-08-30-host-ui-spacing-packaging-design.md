# Host UI Spacing and Windows Packaging Design

**Status:** Approved

**Approved:** 2026-08-30

## Goal

Give the existing PyQt dashboard more consistent breathing room, then produce a
reproducible Windows x64 single-file executable that runs without a separately
installed Python environment. Firmware, SDF1, acquisition behavior, and the
existing dark visual language remain unchanged.

## UI spacing

The selected direction is **B: balanced spacing**. It keeps the 1440x900 live
plot dominant while removing labels and titles that visually touch adjacent
edges.

Use a small semantic spacing scale rather than unrelated literal values:

- 4 px: label-to-value and tightly related inline content;
- 8 px: compact control groups;
- 12 px: ordinary layout gaps and tab vertical padding;
- 16 px: card interiors and section separation;
- 24 px: tab horizontal padding and major group separation.

Apply the scale as follows:

- tabs: 12 px vertical and 24 px horizontal padding, with clear separation
  between the tab strip and page content;
- cards: 16 px interior padding and 14-16 px from heading to content;
- acquisition toolbar: 16 px horizontal and 10 px vertical padding;
- health and attitude metrics: 5 px between label and value, with enough outer
  padding that the first and last cells do not touch the card edge;
- diagnostics and console pages: 16 px page interior padding; console transcript
  and input row separated by 12 px;
- header controls: preserve compact height but add 8 px group spacing and a
  small vertical inset.

The base and metric font sizes stay at 13 px and 16 px. Colors, plot proportions,
two-column attitude grid, and seven-column health strip stay unchanged.

## Packaging architecture

Use PyInstaller in `onefile` and `windowed` mode. The deliverable is named
`STM32SensorHost-<version>-win64.exe`, where `<version>` comes from
`host/pyproject.toml`.

The repository will contain:

- a pinned build requirements file for PyInstaller;
- a checked-in `.spec` file that collects PyQt6, pyqtgraph, PyOpenGL, NumPy, and
  pyserial runtime modules and Qt plugins;
- a PowerShell build script that creates or refreshes an isolated build venv,
  installs the host package and build requirements, cleans prior packaging
  output, builds the executable, runs smoke verification, writes SHA256, and
  emits a JSON artifact manifest;
- an application `--smoke-test` mode that initializes Qt, fonts, theme, the main
  window, and the OpenGL fallback path without opening hardware;
- `docs/HOST_BUILD_ENVIRONMENT.md` with exact clean-machine commands,
  prerequisites, versioning, verification, troubleshooting, and release steps.

The build script accepts an explicit Python path. Its default resolution order
is the configured Codex cached runtime, `py -3.12`, then `python`; it fails with
an actionable message if none is suitable. Build environments and intermediate
PyInstaller output remain ignored. Final artifacts are written below
`dist/host/` and are not committed.

## Verification

UI verification:

- pytest-qt asserts semantic spacing constants and representative layout
  margins for tabs, cards, toolbar, diagnostics, console, attitude, and health;
- regenerate and inspect the deterministic 1920x1080 visual baseline;
- inspect a 1440x900 rendered window for overlap and plot-area regression.

Packaging verification:

- tests cover version-derived artifact naming and build manifest generation;
- the build script runs all host tests before packaging;
- the generated EXE runs `--smoke-test` with `QT_QPA_PLATFORM=offscreen` and
  exits zero;
- the script verifies that the EXE and SHA256 file exist and that the manifest
  records matching size, hash, version, architecture, Python, and PyInstaller
  versions;
- final review runs the repository Stage 1 gate to ensure UI/packaging work did
  not affect firmware.

## Constraints and known trade-offs

- A PyInstaller single-file application extracts bundled files to a temporary
  directory at startup, so first launch is slower than an `onedir` build.
- Unsigned single-file executables can trigger reputation-based antivirus
  warnings. Code signing is outside this task; the SHA256 file provides artifact
  integrity, not publisher identity.
- This package targets Windows x64 only. Cross-platform installers, automatic
  updates, and MSI packaging are out of scope.
