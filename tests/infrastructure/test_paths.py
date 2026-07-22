from pathlib import Path

from listening_cloze.infrastructure.paths import AppPaths, get_app_paths


def test_explicit_root_controls_all_application_paths(tmp_path: Path) -> None:
    root = tmp_path / "portable-data"

    paths = get_app_paths(root=root)

    assert paths == AppPaths(
        root=root,
        content_db=root / "content.db",
        user_db=root / "user.db",
        audio_cache=root / "audio-cache",
        backups=root / "backups",
        logs=root / "logs",
    )


def test_ensure_directories_creates_only_required_directories(tmp_path: Path) -> None:
    paths = get_app_paths(root=tmp_path / "data")

    paths.ensure_directories()

    assert paths.root.is_dir()
    assert paths.audio_cache.is_dir()
    assert paths.backups.is_dir()
    assert paths.logs.is_dir()
    assert not paths.content_db.exists()
    assert not paths.user_db.exists()


def test_windows_defaults_to_local_appdata(tmp_path: Path) -> None:
    paths = get_app_paths(
        platform_name="Windows",
        environ={"LOCALAPPDATA": str(tmp_path)},
    )

    assert paths.root == tmp_path / "ListeningCloze"


def test_environment_can_override_default_data_directory(tmp_path: Path) -> None:
    paths = get_app_paths(
        platform_name="Darwin",
        environ={"LISTENING_CLOZE_DATA_DIR": str(tmp_path / "smoke-data")},
    )

    assert paths.root == tmp_path / "smoke-data"


def test_non_windows_default_comes_from_platformdirs(monkeypatch, tmp_path: Path) -> None:
    expected = tmp_path / "platform-data"
    calls: list[tuple[str, bool]] = []

    def fake_user_data_path(appname: str, *, appauthor: bool) -> Path:
        calls.append((appname, appauthor))
        return expected

    monkeypatch.setattr(
        "listening_cloze.infrastructure.paths.platformdirs.user_data_path",
        fake_user_data_path,
    )

    paths = get_app_paths(platform_name="Darwin")

    assert paths.root == expected
    assert calls == [("ListeningCloze", False)]


def test_windows_requires_local_appdata() -> None:
    try:
        get_app_paths(platform_name="Windows", environ={})
    except RuntimeError as error:
        assert "LOCALAPPDATA" in str(error)
    else:
        raise AssertionError("缺少 LOCALAPPDATA 时应拒绝猜测数据目录")
