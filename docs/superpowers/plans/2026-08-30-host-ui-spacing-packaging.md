# Host UI Spacing and Single-file Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the approved balanced PyQt layout spacing and produce a reproducible Windows x64 single-file `STM32SensorHost-0.1.0-win64.exe` build with automated smoke evidence.

**Architecture:** Keep the existing dashboard structure and introduce one presentation spacing module used by widget layouts and the stylesheet. Keep packaging metadata in a small Qt-free Python module, let PyInstaller consume the existing application entry point, and drive clean builds through a PowerShell script that resolves a cached Python runtime before falling back to installed Python.

**Tech Stack:** Python 3.11+, PyQt6, pyqtgraph, pytest/pytest-qt, PyInstaller 6.16.0, PowerShell, existing STM32 Stage 1 CMake test gate.

---

## File map

- Create `host/src/sensor_host/presentation/spacing.py`: named 4/8/12/16/24 px spacing tokens.
- Modify `host/src/sensor_host/presentation/theme.py`: tab and text-control padding based on spacing tokens.
- Modify `host/src/sensor_host/presentation/main_window.py`: balanced page, toolbar, card, header, and health metric spacing.
- Modify `host/src/sensor_host/presentation/console_view.py`: transcript/input separation.
- Modify `host/src/sensor_host/presentation/diagnostics_view.py`: diagnostics page and section spacing.
- Modify `host/src/sensor_host/presentation/orientation_view.py`: orientation status and numeric metric spacing.
- Modify `host/tests/test_widgets.py`: assert the approved spacing contract.
- Create `host/src/sensor_host/packaging.py`: version, artifact-name, hash, and manifest helpers without Qt imports.
- Modify `host/src/sensor_host/app.py`: accept `--smoke-test` and construct the complete window offscreen without entering the event loop.
- Create `host/tests/test_packaging.py`: package metadata and smoke-mode tests.
- Create `host/requirements-build.txt`: pinned build-only dependency.
- Create `host/STM32SensorHost.spec`: one-file, windowed PyInstaller recipe.
- Create `tools/package_host.ps1`: reproducible venv, test, build, smoke, hash, and manifest workflow.
- Modify `.gitignore`: ignore build environments, intermediates, and generated host artifacts.
- Create `docs/HOST_BUILD_ENVIRONMENT.md`: reusable environment and troubleshooting guide.
- Modify `host/README.md` and `README.md`: link the packaged build workflow.

### Task 1: Define and apply the balanced spacing contract

**Files:**
- Create: `host/src/sensor_host/presentation/spacing.py`
- Modify: `host/src/sensor_host/presentation/theme.py`
- Modify: `host/src/sensor_host/presentation/main_window.py`
- Modify: `host/src/sensor_host/presentation/console_view.py`
- Modify: `host/src/sensor_host/presentation/diagnostics_view.py`
- Modify: `host/src/sensor_host/presentation/orientation_view.py`
- Test: `host/tests/test_widgets.py`

- [ ] **Step 1: Write failing spacing-contract tests**

Add imports and tests that inspect real Qt layouts and the rendered stylesheet:

```python
from sensor_host.presentation.spacing import SPACE
from sensor_host.presentation.theme import dark_stylesheet


def test_balanced_spacing_tokens_are_stable() -> None:
    assert (SPACE.tight, SPACE.compact, SPACE.normal, SPACE.section, SPACE.major) == (
        4, 8, 12, 16, 24
    )


def test_tabs_and_pages_have_breathing_room(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    margins = window.live_tab.layout().contentsMargins()

    assert margins.top() == SPACE.section
    assert window.live_tab.layout().spacing() == SPACE.normal
    assert "padding: 12px 24px" in dark_stylesheet()


def test_card_and_metric_spacing_is_balanced(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    card_margins = window.vibration_container_layout.contentsMargins()
    assert card_margins.left() == SPACE.section
    assert window.vibration_container_layout.spacing() == SPACE.section
    assert window.health_metrics_layout.spacing() == SPACE.compact
    assert all(layout.spacing() == SPACE.tight for layout in window.health_field_layouts)


def test_console_and_diagnostics_pages_use_section_padding(qtbot) -> None:
    console = ConsoleView()
    diagnostics = DiagnosticsView()
    qtbot.addWidget(console)
    qtbot.addWidget(diagnostics)

    assert console.layout().spacing() == SPACE.normal
    margins = diagnostics.grid.contentsMargins()
    assert (margins.left(), margins.top()) == (SPACE.section, SPACE.section)
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_widgets.py -q
```

Expected: collection fails because `sensor_host.presentation.spacing` does not exist.

- [ ] **Step 3: Add immutable semantic spacing tokens**

Create `spacing.py`:

```python
"""Semantic spacing tokens shared by the PyQt presentation layer."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Spacing:
    tight: int = 4
    compact: int = 8
    normal: int = 12
    section: int = 16
    major: int = 24


SPACE = Spacing()
```

- [ ] **Step 4: Apply tokens without changing dashboard proportions**

Import `SPACE` in the affected presentation files and apply these exact values:

```python
# theme.py
QTabBar::tab {{ padding: {SPACE.normal}px {SPACE.major}px; }}

# main_window.py
root_layout.setContentsMargins(SPACE.major, SPACE.section, SPACE.major, SPACE.major)
layout.setContentsMargins(SPACE.section, SPACE.section, SPACE.section, SPACE.section)
layout.setSpacing(SPACE.section)                     # card title to content
header_layout.setSpacing(SPACE.compact)
toolbar_layout.setContentsMargins(SPACE.section, SPACE.compact, SPACE.section, SPACE.compact)
tab_layout.setContentsMargins(0, SPACE.section, 0, 0)
self.health_metrics_layout.setSpacing(SPACE.compact)
field_layout.setContentsMargins(SPACE.compact, SPACE.tight, SPACE.compact, SPACE.tight)
field_layout.setSpacing(SPACE.tight)
self.health_field_layouts.append(field_layout)

# console_view.py
layout.setSpacing(SPACE.normal)
input_row.setSpacing(SPACE.compact)

# diagnostics_view.py
self.grid.setContentsMargins(SPACE.section, SPACE.section, SPACE.section, SPACE.section)
self.grid.setHorizontalSpacing(SPACE.major)
self.grid.setVerticalSpacing(SPACE.compact)

# orientation_view.py
layout.setSpacing(SPACE.compact)
status_row.setSpacing(SPACE.compact)
field_layout.setContentsMargins(SPACE.compact, SPACE.compact, SPACE.compact, SPACE.compact)
field_layout.setSpacing(SPACE.tight)
```

Expose `self.health_metrics_layout` and `self.health_field_layouts` solely as stable UI contract handles for tests. Preserve splitter ratios, widget order, colors, and font sizes.

- [ ] **Step 5: Run UI tests and commit**

Run:

```powershell
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_widgets.py -q
git diff --check
```

Expected: all widget tests pass and `git diff --check` is silent.

Commit:

```powershell
git add host/src/sensor_host/presentation host/tests/test_widgets.py
git commit -m "style(host): improve balanced dashboard spacing"
```

### Task 2: Add deterministic application and packaging metadata smoke tests

**Files:**
- Create: `host/src/sensor_host/packaging.py`
- Modify: `host/src/sensor_host/app.py`
- Test: `host/tests/test_packaging.py`

- [ ] **Step 1: Write failing metadata and application-smoke tests**

Create `test_packaging.py`:

```python
import json

from sensor_host.app import main
from sensor_host.packaging import artifact_name, write_manifest


def test_artifact_name_uses_project_version_and_platform() -> None:
    assert artifact_name() == "STM32SensorHost-0.1.0-win64.exe"


def test_manifest_contains_filename_size_and_sha256(tmp_path) -> None:
    artifact = tmp_path / artifact_name()
    artifact.write_bytes(b"host-executable")

    manifest_path = write_manifest(artifact)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["artifact"] == artifact.name
    assert manifest["bytes"] == len(b"host-executable")
    assert len(manifest["sha256"]) == 64


def test_application_smoke_mode_constructs_window_without_event_loop(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert main(["stm32-sensor-host", "--smoke-test"]) == 0
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_packaging.py -q
```

Expected: collection fails because `sensor_host.packaging` does not exist.

- [ ] **Step 3: Implement Qt-free package metadata helpers**

Create `packaging.py`:

```python
"""Metadata helpers shared by tests and the Windows packaging workflow."""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PROJECT_DISTRIBUTION = "stm32-sensor-host"


def project_version() -> str:
    try:
        return version(PROJECT_DISTRIBUTION)
    except PackageNotFoundError:
        return "0.1.0"


def artifact_name() -> str:
    return f"STM32SensorHost-{project_version()}-win64.exe"


def write_manifest(artifact: Path) -> Path:
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest_path = artifact.with_suffix(".json")
    payload = {"artifact": artifact.name, "bytes": artifact.stat().st_size, "sha256": digest}
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path
```

- [ ] **Step 4: Add non-blocking `--smoke-test` handling**

Change `main` to accept explicit arguments, set offscreen mode before Qt application construction, create the complete window, process queued events, and exit without serial discovery or the event loop:

```python
def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)
    smoke_test = "--smoke-test" in arguments[1:]
    if smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        arguments = [argument for argument in arguments if argument != "--smoke-test"]
    application = QApplication.instance() or QApplication(arguments)
    application.setApplicationName("STM32 Sensor Host")
    load_application_fonts()
    application.setStyleSheet(dark_stylesheet())
    window = MainWindow()
    if smoke_test:
        window.show()
        application.processEvents()
        window.close()
        return 0
    # Existing controller wiring and device refresh remain here.
```

The implementation must not enumerate or open a serial port in smoke mode.

- [ ] **Step 5: Run focused and regression tests, then commit**

Run:

```powershell
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_packaging.py .\host\tests\test_widgets.py -q
```

Expected: all focused tests pass.

Commit:

```powershell
git add host/src/sensor_host/app.py host/src/sensor_host/packaging.py host/tests/test_packaging.py
git commit -m "feat(host): add deterministic packaging smoke mode"
```

### Task 3: Create the reproducible single-file Windows build chain

**Files:**
- Create: `host/requirements-build.txt`
- Create: `host/STM32SensorHost.spec`
- Create: `tools/package_host.ps1`
- Modify: `.gitignore`
- Test: `host/tests/test_packaging.py`

- [ ] **Step 1: Write failing source-contract tests**

Append:

```python
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_pyinstaller_recipe_is_windowed_onefile() -> None:
    recipe = (REPOSITORY_ROOT / "host" / "STM32SensorHost.spec").read_text(encoding="utf-8")
    assert "console=False" in recipe
    assert "EXE(" in recipe
    assert "COLLECT(" not in recipe


def test_build_dependency_is_pinned() -> None:
    requirements = (REPOSITORY_ROOT / "host" / "requirements-build.txt").read_text(encoding="utf-8")
    assert requirements.strip() == "pyinstaller==6.16.0"
```

- [ ] **Step 2: Run the source-contract tests and confirm RED**

Run:

```powershell
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_packaging.py -q
```

Expected: failure because the spec and build requirements do not exist.

- [ ] **Step 3: Pin the build dependency and add a one-file spec**

Create `requirements-build.txt` containing exactly:

```text
pyinstaller==6.16.0
```

Create `STM32SensorHost.spec` with `host/src` in `pathex`, `sensor_host.app` as the entry, `collect_all()` for `pyqtgraph` and `OpenGL`, and one `EXE` node containing `a.binaries` and `a.datas`. Set `name=artifact_name()[:-4]`, `console=False`, `debug=False`, and `upx=False`; do not add a `COLLECT` node.

- [ ] **Step 4: Add the clean PowerShell build orchestrator**

Implement `tools/package_host.ps1` with:

```powershell
param([string]$Python, [switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$HostRoot = Join-Path $RepositoryRoot 'host'
$BuildRoot = Join-Path $RepositoryRoot 'build\host-package'
$VenvPython = Join-Path $BuildRoot '.venv\Scripts\python.exe'
$ArtifactRoot = Join-Path $RepositoryRoot 'dist\host'
```

Python resolution order must be: explicit `-Python`, cached Codex runtime at `C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`, `py -3.12`, then `python`. The script must recreate only `build/host-package`, install `host[dev]` and `requirements-build.txt`, run the host/protocol suite unless `-SkipTests`, invoke PyInstaller with `--clean --noconfirm`, move the versioned EXE to `dist/host`, run it as `--smoke-test`, fail on a non-zero exit, and invoke `sensor_host.packaging.write_manifest` for the final artifact.

Add ignores:

```gitignore
build/host-package/
dist/host/
```

- [ ] **Step 5: Run contract tests and commit**

Run:

```powershell
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_packaging.py -q
git diff --check
```

Expected: all packaging source-contract tests pass.

Commit:

```powershell
git add .gitignore host/requirements-build.txt host/STM32SensorHost.spec tools/package_host.ps1 host/tests/test_packaging.py
git commit -m "build(host): add reproducible single-file packaging"
```

### Task 4: Document the reusable build environment

**Files:**
- Create: `docs/HOST_BUILD_ENVIRONMENT.md`
- Modify: `host/README.md`
- Modify: `README.md`

- [ ] **Step 1: Write the reusable environment guide**

Document these exact sections in `docs/HOST_BUILD_ENVIRONMENT.md`:

1. Supported output: Windows 10/11 x64, single-file/windowed, unsigned.
2. One-command build: `.\tools\package_host.ps1`.
3. Explicit runtime: `.\tools\package_host.ps1 -Python 'C:\path\to\python.exe'`.
4. Resolution order and isolated `build/host-package/.venv` behavior.
5. Output files: versioned EXE and same-stem JSON manifest in `dist/host`.
6. Verification: source tests, packaged `--smoke-test`, SHA-256 check with `Get-FileHash`.
7. Rebuild/upgrade procedure: change the PyInstaller pin, run the full command, inspect warnings, rerun Stage 1.
8. Troubleshooting: antivirus false positives, one-file extraction latency, missing MSVC runtime/Qt plugins, OpenGL fallback, and unsigned binary warning.

- [ ] **Step 2: Link the workflow from both READMEs**

Add a `Packaged Windows build` section to `host/README.md` containing the one-command build, output path, and a relative link to `../docs/HOST_BUILD_ENVIRONMENT.md`. Add a short `Host packaging` link in the root README without duplicating the guide.

- [ ] **Step 3: Verify docs and commit**

Run:

```powershell
rg -n "package_host|STM32SensorHost|HOST_BUILD_ENVIRONMENT|sha256" docs/HOST_BUILD_ENVIRONMENT.md host/README.md README.md
git diff --check
```

Expected: both READMEs link to the guide and the guide contains build, artifact, smoke, and checksum instructions.

Commit:

```powershell
git add docs/HOST_BUILD_ENVIRONMENT.md host/README.md README.md
git commit -m "docs: add reusable host packaging environment"
```

### Task 5: Produce and inspect completion evidence

**Files:**
- Modify: `host/tests/golden/visual/dark-live-monitor.png`
- Generate, do not commit: `dist/host/STM32SensorHost-0.1.0-win64.exe`
- Generate, do not commit: `dist/host/STM32SensorHost-0.1.0-win64.json`

- [ ] **Step 1: Run the complete source gate**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests .\test\test_protocol.py -q
& .\host\.venv\Scripts\python.exe -m compileall -q .\host\src .\host\tools
Remove-Item Env:QT_QPA_PLATFORM
```

Expected: all Python tests pass and compileall is silent.

- [ ] **Step 2: Regenerate and inspect the visual baseline**

Run:

```powershell
& .\host\.venv\Scripts\python.exe .\host\tools\capture_visual_baseline.py
```

Inspect `host/tests/golden/visual/dark-live-monitor.png` at original resolution. Confirm tab padding, card-title separation, health label/value separation, diagnostic margins, and console transcript/input gap; reject clipping, crowding, or changed splitter proportions.

- [ ] **Step 3: Build and smoke-test the final executable**

Run:

```powershell
.\tools\package_host.ps1
Get-ChildItem .\dist\host\STM32SensorHost-0.1.0-win64.*
Get-FileHash .\dist\host\STM32SensorHost-0.1.0-win64.exe -Algorithm SHA256
```

Expected: one EXE and one JSON manifest exist, the script reports a zero smoke-test exit, and the displayed hash matches the manifest.

- [ ] **Step 4: Run the firmware regression gate**

Run:

```powershell
.\tools\test_stage1.ps1
```

Expected: cached CMake build completes and all Stage 1 firmware tests pass.

- [ ] **Step 5: Review, commit the baseline if changed, and prepare merge**

Run:

```powershell
git status --short
git diff --check
git diff --stat master...HEAD
```

Commit only the intended visual baseline if it changed:

```powershell
git add host/tests/golden/visual/dark-live-monitor.png
git commit -m "test(host): refresh balanced UI visual baseline"
```

Do not stage `.clangd`, `docs/JY61PL_iis3dwb/`, `dist/host/`, or any build environment. Perform final requirements/code review, then merge `codex/host-ui-package` into `master` only after all evidence above is current.
