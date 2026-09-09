"""PyInstaller recipe for the windowed single-file Windows host."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

from sensor_host.packaging import artifact_name

WINDOWS_SYSTEM_ICU_DLLS = {"icuuc.dll", "icudt78.dll"}


host_root = Path(SPECPATH).resolve()
source_root = host_root / "src"
entry_point = source_root / "sensor_host" / "app.py"
application_icon = source_root / "sensor_host" / "assets" / "vibration_sensor_icon.ico"

datas = [
    (
        str(source_root / "sensor_host" / "assets" / "vibration_sensor_icon.png"),
        "sensor_host/assets",
    )
]
binaries = []
hiddenimports = []
for package_name in ("pyqtgraph", "OpenGL"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)

analysis = Analysis(
    [str(entry_point)],
    pathex=[str(source_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
analysis.binaries = [
    binary
    for binary in analysis.binaries
    if binary[0].lower() not in WINDOWS_SYSTEM_ICU_DLLS
]
python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=artifact_name()[:-4],
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(application_icon),
)
