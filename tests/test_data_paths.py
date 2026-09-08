from sensor_host.storage.paths import data_root


def test_default_storage_does_not_follow_working_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("SENSOR_HOST_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    monkeypatch.chdir(tmp_path)
    assert data_root() == tmp_path / "profile" / "SensorHost"


def test_explicit_storage_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SENSOR_HOST_DATA_DIR", str(tmp_path / "captures"))
    assert data_root() == tmp_path / "captures"
