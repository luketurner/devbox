import devbox


def test_package_has_version():
    assert isinstance(devbox.__version__, str)
    assert devbox.__version__
