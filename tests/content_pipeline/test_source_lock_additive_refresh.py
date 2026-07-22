from __future__ import annotations

import bz2
import json
import zipfile
from pathlib import Path

import pytest

from tools.content_pipeline import production_sources
from tools.content_pipeline.production_sources import (
    import_all_sources,
    verify_source_lock,
)
from tools.content_pipeline.work_database import WorkDatabase


def _write_tatoeba(tmp_path: Path) -> dict[str, object]:
    archive = tmp_path / "tatoeba.tsv.bz2"
    with bz2.open(archive, "wt", encoding="utf-8") as stream:
        stream.write("1\teng\tThe train arrives at nine.\talice\n")
    return {"key": "tatoeba-eng", "kind": "tatoeba", "url": archive.as_uri()}


def _write_daily_dialog(tmp_path: Path) -> dict[str, object]:
    archive = tmp_path / "daily-dialog.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "ijcnlp_dailydialog/dialogues_text.txt",
            "The hotel is near the station. __eou__ Thank you for your help. __eou__\n",
        )
    return {"key": "daily-dialog", "kind": "dailydialog", "url": archive.as_uri()}


def _write_manifest(path: Path, sources: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(sources), encoding="utf-8")


def _initialized_database(path: Path) -> WorkDatabase:
    database = WorkDatabase(path)
    database.initialize()
    return database


def test_additive_refresh_checkpoints_new_identity_before_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _initialized_database(tmp_path / "work.db")
    base = _write_tatoeba(tmp_path)
    added = _write_daily_dialog(tmp_path)
    manifest = tmp_path / "manifest.json"
    lock = tmp_path / "source-lock.json"
    _write_manifest(manifest, [base])
    import_all_sources(database, manifest, lock)
    _write_manifest(manifest, [base, added])
    original_download = production_sources._download_locked

    def interrupt_added_download(key: str, *args, **kwargs):
        if key == "daily-dialog":
            raise RuntimeError("simulated added-source download interruption")
        return original_download(key, *args, **kwargs)

    monkeypatch.setattr(production_sources, "_download_locked", interrupt_added_download)
    with pytest.raises(RuntimeError, match="download interruption"):
        import_all_sources(database, manifest, lock, refresh_lock=True)

    interrupted = json.loads(lock.read_text(encoding="utf-8"))
    assert interrupted["pending_refresh_identities"] == ["daily-dialog"]
    assert interrupted["complete"] is False
    assert [entry["key"] for entry in interrupted["sources"]] == ["tatoeba-eng"]


def test_interrupted_additive_import_resumes_without_refresh_flag_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _initialized_database(tmp_path / "work.db")
    base = _write_tatoeba(tmp_path)
    added = _write_daily_dialog(tmp_path)
    manifest = tmp_path / "manifest.json"
    lock = tmp_path / "source-lock.json"
    _write_manifest(manifest, [base])
    import_all_sources(database, manifest, lock)
    _write_manifest(manifest, [base, added])
    original_iter_source = production_sources._iter_source

    def interrupt_added_import(kind: str, *args, **kwargs):
        if kind == "dailydialog":
            raise RuntimeError("simulated added-source import interruption")
        return original_iter_source(kind, *args, **kwargs)

    monkeypatch.setattr(production_sources, "_iter_source", interrupt_added_import)
    with pytest.raises(RuntimeError, match="import interruption"):
        import_all_sources(database, manifest, lock, refresh_lock=True)
    interrupted = json.loads(lock.read_text(encoding="utf-8"))
    assert interrupted["pending_refresh_identities"] == ["daily-dialog"]
    assert interrupted["complete"] is False
    monkeypatch.setattr(production_sources, "_iter_source", original_iter_source)

    import_all_sources(database, manifest, lock)
    import_all_sources(database, manifest, lock)

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT source_name, source_item_id, source_author "
            "FROM raw_items ORDER BY source_name, source_item_id"
        ).fetchall()
    assert rows == [
        ("Tatoeba", "1", "alice"),
        ("daily-dialog", "dialogue:1:turn:1", ""),
        ("daily-dialog", "dialogue:1:turn:2", ""),
    ]
    completed = json.loads(lock.read_text(encoding="utf-8"))
    assert completed["pending_refresh_identities"] == []
    assert completed["complete"] is True


@pytest.mark.parametrize("mutation", ["delete", "rename"])
def test_additive_refresh_rejects_deleted_or_renamed_existing_key(
    tmp_path: Path, mutation: str
) -> None:
    database = _initialized_database(tmp_path / "work.db")
    base = _write_tatoeba(tmp_path)
    manifest = tmp_path / "manifest.json"
    lock = tmp_path / "source-lock.json"
    _write_manifest(manifest, [base])
    import_all_sources(database, manifest, lock)
    if mutation == "delete":
        changed: list[dict[str, object]] = []
    else:
        changed = [base | {"key": "renamed-tatoeba"}]
    _write_manifest(manifest, changed)

    with pytest.raises(ValueError, match="不允许删除或重命名来源 key"):
        import_all_sources(database, manifest, lock, refresh_lock=True)


def test_additive_refresh_rejects_identity_change_for_existing_key(tmp_path: Path) -> None:
    database = _initialized_database(tmp_path / "work.db")
    base = _write_tatoeba(tmp_path)
    daily = _write_daily_dialog(tmp_path)
    manifest = tmp_path / "manifest.json"
    lock = tmp_path / "source-lock.json"
    _write_manifest(manifest, [base])
    import_all_sources(database, manifest, lock)
    changed = daily | {"key": "tatoeba-eng"}
    _write_manifest(manifest, [changed])

    with pytest.raises(ValueError, match="禁止改变来源 identity"):
        import_all_sources(database, manifest, lock, refresh_lock=True)


def test_identity_change_is_rejected_before_additive_lock_checkpoint(tmp_path: Path) -> None:
    database = _initialized_database(tmp_path / "work.db")
    base = _write_tatoeba(tmp_path)
    daily = _write_daily_dialog(tmp_path)
    manifest = tmp_path / "manifest.json"
    lock = tmp_path / "source-lock.json"
    _write_manifest(manifest, [base])
    import_all_sources(database, manifest, lock)
    locked_before = lock.read_bytes()
    changed_base = daily | {"key": "tatoeba-eng"}
    _write_manifest(manifest, [changed_base, daily])

    with pytest.raises(ValueError, match="禁止改变来源 identity"):
        import_all_sources(database, manifest, lock, refresh_lock=True)

    assert lock.read_bytes() == locked_before


def test_dialogue_source_cache_checksum_is_verified(tmp_path: Path) -> None:
    database = _initialized_database(tmp_path / "work.db")
    daily = _write_daily_dialog(tmp_path)
    manifest = tmp_path / "manifest.json"
    lock = tmp_path / "source-lock.json"
    _write_manifest(manifest, [daily])
    import_all_sources(database, manifest, lock)
    entry = json.loads(lock.read_text(encoding="utf-8"))["sources"][0]
    cached = lock.parent / entry["cache_path"]
    cached.write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="缓存校验失败"):
        verify_source_lock(lock)
