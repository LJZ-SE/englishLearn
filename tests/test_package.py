from listening_cloze import APP_NAME, __version__


def test_package_exposes_application_identity() -> None:
    assert APP_NAME == "听写填空"
    assert __version__ == "0.1.0"
