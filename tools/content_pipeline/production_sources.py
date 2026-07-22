from __future__ import annotations

import hashlib
import json
import sqlite3
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.content_pipeline.convokit_source import iter_convokit_utterances
from tools.content_pipeline.gutenberg import iter_gutenberg_text
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.tatoeba import iter_tatoeba_detailed
from tools.content_pipeline.wikinews import iter_wikinews_extracts
from tools.content_pipeline.work_database import WorkDatabase

_CONVOKIT_URL = (
    "https://zissou.infosci.cornell.edu/convokit/datasets/{name}/{name}.zip"
)
_WIKINEWS_QUERY = {
    "action": "query",
    "generator": "categorymembers",
    "gcmtitle": "Category:Published",
    "gcmtype": "page",
    "gcmlimit": "500",
    "prop": "extracts|info",
    "explaintext": "1",
    "inprop": "url",
    "format": "json",
    "formatversion": "2",
}


def import_all_sources(
    database: WorkDatabase,
    manifest_path: Path,
    lock_path: Path,
) -> dict[str, int]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, list):
        raise ValueError("来源 manifest 必须是数组")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    cache_root = lock_path.parent / "downloads"
    cache_root.mkdir(parents=True, exist_ok=True)
    existing = _read_lock(lock_path)
    locked: list[dict[str, Any]] = []
    imported: Counter[str] = Counter()

    for source in _expanded_sources(manifest):
        key = _required_string(source, "key")
        kind = _required_string(source, "kind")
        url = _source_url(source)
        cache_path = cache_root / _cache_filename(key, url)
        entry = _download_locked(key, kind, url, cache_path, existing.get(key))
        locked.append(entry)
        _checkpoint_source_lock(lock_path, manifest_path, locked, existing)
        items = _iter_source(kind, cache_path, source)
        imported[kind] += _import_items(database, items, source.get("max_items"))

    _checkpoint_source_lock(lock_path, manifest_path, locked, {})
    return dict(imported)


def import_legacy_database(
    legacy_path: Path,
    database: WorkDatabase,
    *,
    protected: bool,
) -> int:
    _ensure_legacy_schema(database)
    with sqlite3.connect(legacy_path) as legacy:
        sentences = legacy.execute(
            """
            SELECT id, text, source_url, license_name, license_url, source_author,
                   normalized_hash
            FROM sentences
            ORDER BY id
            """
        ).fetchall()
        questions = legacy.execute(
            """
            SELECT id, sentence_id, difficulty, canonical_answer
            FROM question_variants
            ORDER BY id
            """
        ).fetchall()
        aliases = legacy.execute(
            "SELECT question_variant_id, alias FROM aliases ORDER BY question_variant_id, alias"
        ).fetchall()

    if len({str(row[6]) for row in sentences}) != len(sentences):
        raise ValueError("旧题库存在重复 normalized_hash")
    item_ids: dict[str, int] = {}
    for sentence_id, text, source_url, license_name, license_url, author, _digest in sentences:
        item_ids[str(sentence_id)] = database.upsert_raw(
            source_name="legacy-content",
            source_item_id=str(sentence_id),
            source_url=str(source_url),
            source_author=str(author),
            license_name=str(license_name),
            license_url=str(license_url),
            text=str(text),
            protected=protected,
        )

    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            """
            INSERT INTO legacy_sentences(item_id, sentence_id, normalized_hash)
            VALUES (?, ?, ?)
            ON CONFLICT(sentence_id) DO UPDATE SET
                item_id = excluded.item_id,
                normalized_hash = excluded.normalized_hash
            """,
            [(item_ids[str(row[0])], str(row[0]), str(row[6])) for row in sentences],
        )
        connection.executemany(
            """
            INSERT INTO legacy_questions(item_id, question_id, difficulty, canonical_answer)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(question_id) DO UPDATE SET
                item_id = excluded.item_id,
                difficulty = excluded.difficulty,
                canonical_answer = excluded.canonical_answer
            """,
            [
                (item_ids[str(sentence_id)], str(question_id), str(difficulty), str(answer))
                for question_id, sentence_id, difficulty, answer in questions
            ],
        )
        connection.execute("DELETE FROM legacy_aliases")
        connection.executemany(
            "INSERT INTO legacy_aliases(question_id, alias) VALUES (?, ?)",
            [(str(question_id), str(alias)) for question_id, alias in aliases],
        )
    return len(sentences)


def report_sources(database: WorkDatabase, output_path: Path) -> dict[str, Any]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT source_name, source_item_id, license_name, license_url, COUNT(*)
            FROM raw_items
            GROUP BY source_name, source_item_id, license_name, license_url
            """
        ).fetchall()
        source_counts = connection.execute(
            "SELECT source_name, COUNT(*) FROM raw_items GROUP BY source_name ORDER BY source_name"
        ).fetchall()
    missing = sum(
        int(not str(value).strip())
        for row in rows
        for value in (row[0], row[1], row[2], row[3])
    )
    kinds = sorted({_source_kind(str(name)) for name, _ in source_counts})
    report = {
        "raw_count": sum(int(count) for _, count in source_counts),
        "source_kind_count": len(kinds),
        "source_kinds": kinds,
        "source_counts": {str(name): int(count) for name, count in source_counts},
        "missing_provenance_count": missing,
    }
    _atomic_write_json(output_path, report)
    if missing:
        raise ValueError(f"来源报告发现 {missing} 个空溯源字段")
    return report


def verify_source_lock(lock_path: Path) -> None:
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    for entry in payload.get("sources", []):
        cache_path = lock_path.parent / str(entry["cache_path"])
        if not cache_path.is_file():
            raise ValueError(f"冻结来源缓存不存在: {cache_path}")
        size, digest = _file_fingerprint(cache_path)
        if size != int(entry["size_bytes"]) or digest != str(entry["sha256"]):
            raise ValueError(f"冻结来源缓存校验失败: {cache_path}")


def _expanded_sources(manifest: list[object]) -> Iterator[dict[str, Any]]:
    for raw in manifest:
        if not isinstance(raw, dict):
            raise ValueError("来源 manifest 条目必须是对象")
        source = dict(raw)
        if source.get("kind") == "gutenberg" and "ebook_ids" in source:
            for ebook_id in source["ebook_ids"]:
                yield source | {"key": f"gutenberg-{ebook_id}", "ebook_id": int(ebook_id)}
            continue
        yield source


def _source_url(source: dict[str, Any]) -> str:
    kind = _required_string(source, "kind")
    if kind == "convokit" and not source.get("url"):
        name = _required_string(source, "download_name")
        return _CONVOKIT_URL.format(name=name)
    if kind == "gutenberg" and "ebook_id" in source and not source.get("url"):
        ebook_id = int(source["ebook_id"])
        return f"https://www.gutenberg.org/cache/epub/{ebook_id}/pg{ebook_id}.txt"
    url = _required_string(source, "url")
    if kind == "wikinews" and url.startswith(("http://", "https://")) and "?" not in url:
        return f"{url}?{urllib.parse.urlencode(_WIKINEWS_QUERY)}"
    if kind == "gutenberg" and "ebook_id" in source and url.endswith("/ebooks"):
        ebook_id = int(source["ebook_id"])
        return f"https://www.gutenberg.org/cache/epub/{ebook_id}/pg{ebook_id}.txt"
    if kind == "gutenberg" and "ebook_id" in source and "ebook_ids" in source:
        ebook_id = int(source["ebook_id"])
        return f"https://www.gutenberg.org/cache/epub/{ebook_id}/pg{ebook_id}.txt"
    return url


def _download_locked(
    key: str,
    kind: str,
    url: str,
    cache_path: Path,
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    if existing and cache_path.is_file():
        size, digest = _file_fingerprint(cache_path)
        if size == existing.get("size_bytes") and digest == existing.get("sha256"):
            return dict(existing)
    request = urllib.request.Request(url, headers={"User-Agent": "listening-cloze/0.1"})
    temporary = cache_path.with_suffix(cache_path.suffix + ".part")
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as target:
        while chunk := response.read(1024 * 1024):
            target.write(chunk)
        final_url = response.geturl()
    temporary.replace(cache_path)
    size, digest = _file_fingerprint(cache_path)
    return {
        "key": key,
        "kind": kind,
        "requested_url": url,
        "final_url": final_url,
        "cache_path": str(cache_path.relative_to(cache_path.parent.parent)),
        "size_bytes": size,
        "sha256": digest,
        "downloaded_at": datetime.now(UTC).isoformat(),
    }


def _iter_source(
    kind: str, cache_path: Path, source: dict[str, Any]
) -> Iterable[CollectedSentence]:
    if kind == "tatoeba":
        return iter_tatoeba_detailed(cache_path)
    if kind == "convokit":
        extracted = cache_path.parent / f"{cache_path.stem}-extracted"
        utterances = extracted / "utterances.jsonl"
        if not utterances.is_file():
            _extract_convokit(cache_path, extracted)
        source_name = _required_string(source, "key")
        return iter_convokit_utterances(extracted, source_name)
    if kind == "wikinews":
        return iter_wikinews_extracts(cache_path)
    if kind == "gutenberg":
        return iter_gutenberg_text(cache_path, int(source["ebook_id"]))
    raise ValueError(f"不支持的来源类型: {kind}")


def _extract_convokit(archive_path: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            basename = Path(name).name
            if basename not in {"utterances.jsonl", "speakers.json"}:
                continue
            (output / basename).write_bytes(archive.read(name))
    if not (output / "utterances.jsonl").is_file():
        raise ValueError(f"ConvoKit 压缩包缺少 utterances.jsonl: {archive_path}")


def _import_items(
    database: WorkDatabase,
    items: Iterable[CollectedSentence],
    max_items: object,
) -> int:
    limit = int(max_items) if max_items is not None else None
    count = 0
    for item in items:
        missing = [
            field
            for field in (
                "source_name",
                "source_item_id",
                "source_url",
                "source_author",
                "license_name",
                "license_url",
            )
            if not getattr(item, field).strip()
        ]
        if missing:
            raise ValueError(f"来源条目缺少必需溯源字段: {', '.join(missing)}")
        database.upsert_raw(
            source_name=item.source_name,
            source_item_id=item.source_item_id,
            source_url=item.source_url,
            source_author=item.source_author,
            license_name=item.license_name,
            license_url=item.license_url,
            text=item.text,
            top_scene=item.top_scene,
            sub_scene=item.sub_scene,
        )
        count += 1
        if limit is not None and count >= limit:
            break
    return count


def _ensure_legacy_schema(database: WorkDatabase) -> None:
    with database.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS legacy_sentences(
                item_id INTEGER NOT NULL UNIQUE REFERENCES raw_items(id),
                sentence_id TEXT PRIMARY KEY,
                normalized_hash TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS legacy_questions(
                item_id INTEGER NOT NULL REFERENCES raw_items(id),
                question_id TEXT PRIMARY KEY,
                difficulty TEXT NOT NULL,
                canonical_answer TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS legacy_aliases(
                question_id TEXT NOT NULL REFERENCES legacy_questions(question_id),
                alias TEXT NOT NULL,
                PRIMARY KEY(question_id, alias)
            );
            """
        )


def _source_kind(source_name: str) -> str:
    known = {
        "Tatoeba": "tatoeba",
        "English Wikinews": "wikinews",
        "Project Gutenberg": "gutenberg",
        "legacy-content": "legacy",
    }
    if source_name in {"cornell-movie-dialogs", "switchboard"}:
        return "convokit"
    return known.get(source_name, source_name)


def _cache_filename(key: str, url: str) -> str:
    suffixes = "".join(Path(urllib.parse.urlparse(url).path).suffixes)
    return f"{key}{suffixes or '.json'}"


def _file_fingerprint(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _read_lock(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(entry["key"]): entry for entry in payload.get("sources", [])}


def _checkpoint_source_lock(
    lock_path: Path,
    manifest_path: Path,
    locked: list[dict[str, Any]],
    existing: dict[str, dict[str, Any]],
) -> None:
    completed_keys = {str(entry["key"]) for entry in locked}
    sources = [
        *locked,
        *(entry for key, entry in existing.items() if key not in completed_keys),
    ]
    _atomic_write_json(
        lock_path,
        {
            "version": 1,
            "manifest": str(manifest_path),
            "sources": sources,
        },
    )


def _required_string(source: dict[str, Any], field: str) -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"来源 manifest 缺少字段: {field}")
    return value


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
