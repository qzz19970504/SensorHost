from sensor_host import __version__


def test_package_has_development_version() -> None:
    assert __version__ == "0.1.0"
