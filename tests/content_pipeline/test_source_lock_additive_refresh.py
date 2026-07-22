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
            "data/dialogues.json",
            json.dumps(
                [
                    {
                        "dialogue_id": "dailydialog-test-1",
                        "original_id": "test-1",
                        "turns": [
                            {
                                "utt_idx": 0,
                                "utterance": "The hotel is near the station.",
                            },
                            {
                                "utt_idx": 1,
                                "utterance": "Thank you for your help.",
                            },
                        ],
                    }
                ]
            ),
        )
    return {"key": "daily-dialog", "kind": "dailydialog", "url": archive.as_uri()}


def _write_gutenberg_source(
    tmp_path: Path, key: str, ebook_id: int
) -> dict[str, object]:
    text = tmp_path / f"pg{ebook_id}.txt"
    text.write_text(
        f"Author: Sample Author {ebook_id}\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK SAMPLE ***\n"
        f"This is the complete sample sentence for ebook {ebook_id}.\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK SAMPLE ***\n",
        encoding="utf-8",
    )
    return {
        "key": key,
        "kind": "gutenberg",
        "ebook_id": ebook_id,
        "url": text.as_uri(),
    }


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
        ("daily-dialog", "test-1:turn:0", ""),
        ("daily-dialog", "test-1:turn:1", ""),
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


def test_initial_import_second_download_interruption_resumes_without_refresh_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _initialized_database(tmp_path / "work.db")
    base = _write_tatoeba(tmp_path)
    added = _write_daily_dialog(tmp_path)
    manifest = tmp_path / "manifest.json"
    lock = tmp_path / "source-lock.json"
    _write_manifest(manifest, [base, added])
    original_download = production_sources._download_locked

    def interrupt_second_download(key: str, *args, **kwargs):
        if key == "daily-dialog":
            raise RuntimeError("simulated second download interruption")
        return original_download(key, *args, **kwargs)

    monkeypatch.setattr(production_sources, "_download_locked", interrupt_second_download)
    with pytest.raises(RuntimeError, match="second download interruption"):
        import_all_sources(database, manifest, lock)

    interrupted = json.loads(lock.read_text(encoding="utf-8"))
    assert interrupted["pending_refresh_identities"] == ["Tatoeba", "daily-dialog"]
    assert interrupted["complete"] is False
    assert [entry["key"] for entry in interrupted["sources"]] == ["tatoeba-eng"]

    monkeypatch.setattr(production_sources, "_download_locked", original_download)
    import_all_sources(database, manifest, lock)

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0] == 3
    completed = json.loads(lock.read_text(encoding="utf-8"))
    assert completed["pending_refresh_identities"] == []
    assert completed["complete"] is True


def test_shared_identity_addition_before_old_key_resumes_without_refresh_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _initialized_database(tmp_path / "work.db")
    old_source = _write_gutenberg_source(tmp_path, "gutenberg-80", 80)
    new_source = _write_gutenberg_source(tmp_path, "gutenberg-81", 81)
    manifest = tmp_path / "manifest.json"
    lock = tmp_path / "source-lock.json"
    _write_manifest(manifest, [old_source])
    import_all_sources(database, manifest, lock)
    _write_manifest(manifest, [new_source, old_source])
    original_download = production_sources._download_locked

    def interrupt_new_key(key: str, *args, **kwargs):
        if key == "gutenberg-81":
            raise RuntimeError("simulated shared identity interruption")
        return original_download(key, *args, **kwargs)

    monkeypatch.setattr(production_sources, "_download_locked", interrupt_new_key)
    with pytest.raises(RuntimeError, match="shared identity interruption"):
        import_all_sources(database, manifest, lock, refresh_lock=True)

    interrupted = json.loads(lock.read_text(encoding="utf-8"))
    assert interrupted["pending_refresh_identities"] == ["Project Gutenberg"]
    assert interrupted["complete"] is False

    monkeypatch.setattr(production_sources, "_download_locked", original_download)
    import_all_sources(database, manifest, lock)

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT source_item_id FROM raw_items "
            "WHERE source_name = 'Project Gutenberg' ORDER BY source_item_id"
        ).fetchall()
    assert rows == [("80:1",), ("81:1",)]


def test_zip_source_rejects_http_200_html_before_cache_and_lock_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _initialized_database(tmp_path / "work.db")
    manifest = tmp_path / "manifest.json"
    lock = tmp_path / "source-lock.json"
    _write_manifest(
        manifest,
        [
            {
                "key": "daily-dialog",
                "kind": "dailydialog",
                "url": "https://example.test/data.zip",
            }
        ],
    )

    def write_html(_url: str, target: Path) -> str:
        target.write_text("<html>not a zip archive</html>", encoding="utf-8")
        return "https://example.test/login"

    monkeypatch.setattr(production_sources, "_download_url", write_html)
    with pytest.raises(ValueError, match="不是有效 ZIP"):
        import_all_sources(database, manifest, lock)

    interrupted = json.loads(lock.read_text(encoding="utf-8"))
    assert interrupted["sources"] == []
    assert not (lock.parent / "downloads/daily-dialog.zip").exists()
    assert not (lock.parent / "downloads/daily-dialog.zip.part").exists()


def test_zip_source_rejects_missing_minimum_schema(tmp_path: Path) -> None:
    database = _initialized_database(tmp_path / "work.db")
    archive = tmp_path / "multiwoz.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("index.html", "not the expected dataset")
    manifest = tmp_path / "manifest.json"
    lock = tmp_path / "source-lock.json"
    _write_manifest(
        manifest,
        [{"key": "multiwoz", "kind": "multiwoz", "url": archive.as_uri()}],
    )

    with pytest.raises(ValueError, match="缺少最低数据结构"):
        import_all_sources(database, manifest, lock)

    assert not (lock.parent / "downloads/multiwoz.zip").exists()


def test_manifest_expected_sha256_is_checked_before_cache_replace(tmp_path: Path) -> None:
    database = _initialized_database(tmp_path / "work.db")
    daily = _write_daily_dialog(tmp_path) | {"expected_sha256": "0" * 64}
    manifest = tmp_path / "manifest.json"
    lock = tmp_path / "source-lock.json"
    _write_manifest(manifest, [daily])

    with pytest.raises(ValueError, match="SHA-256 不匹配"):
        import_all_sources(database, manifest, lock)

    assert not (lock.parent / "downloads/daily-dialog.zip").exists()
