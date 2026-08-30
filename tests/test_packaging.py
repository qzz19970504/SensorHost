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


def test_application_smoke_mode_constructs_window_without_event_loop(
    monkeypatch, qapp
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    original_stylesheet = qapp.styleSheet()

    assert main(["stm32-sensor-host", "--smoke-test"]) == 0
    assert qapp.styleSheet() == original_stylesheet
