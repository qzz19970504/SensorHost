import json
from pathlib import Path

from sensor_host.app import main
from sensor_host.packaging import artifact_name, main as packaging_main, write_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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


def test_packaging_module_writes_manifest_from_path_argument(tmp_path) -> None:
    artifact = tmp_path / artifact_name()
    artifact.write_bytes(b"packaged-host")

    assert packaging_main([str(artifact)]) == 0
    assert artifact.with_suffix(".json").exists()


def test_application_smoke_mode_constructs_window_without_event_loop(
    monkeypatch, qapp
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    original_stylesheet = qapp.styleSheet()

    assert main(["stm32-sensor-host", "--smoke-test"]) == 0
    assert qapp.styleSheet() == original_stylesheet


def test_pyinstaller_recipe_is_windowed_onefile() -> None:
    recipe = (REPOSITORY_ROOT / "STM32SensorHost.spec").read_text(
        encoding="utf-8"
    )

    assert "console=False" in recipe
    assert "EXE(" in recipe
    assert "COLLECT(" not in recipe


def test_pyinstaller_recipe_excludes_foreign_system_icu() -> None:
    recipe = (REPOSITORY_ROOT / "STM32SensorHost.spec").read_text(
        encoding="utf-8"
    )

    assert "WINDOWS_SYSTEM_ICU_DLLS" in recipe
    assert '"icuuc.dll"' in recipe
    assert '"icudt78.dll"' in recipe


def test_build_dependency_is_pinned() -> None:
    requirements = (
        REPOSITORY_ROOT / "requirements-build.txt"
    ).read_text(encoding="utf-8")

    assert requirements.strip() == "pyinstaller==6.16.0"


def test_build_script_runs_tests_smoke_and_manifest() -> None:
    script = (REPOSITORY_ROOT / "tools" / "package_host.ps1").read_text(
        encoding="utf-8"
    )

    assert "(Join-Path $HostRoot 'tests') -q" in script
    assert "--smoke-test" in script
    assert "sensor_host.packaging" in script


def test_build_script_terminates_the_onefile_process_tree_on_timeout() -> None:
    script = (REPOSITORY_ROOT / "tools" / "package_host.ps1").read_text(
        encoding="utf-8"
    )

    assert "taskkill.exe" in script
    assert "'/T'" in script
