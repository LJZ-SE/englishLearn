from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import urllib.error
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
    "gcmlimit": "20",
    "prop": "extracts|info",
    "explaintext": "1",
    "exintro": "1",
    "exlimit": "20",
    "inprop": "url",
    "format": "json",
    "formatversion": "2",
}
_SAFE_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LOCK_VERSION = 2


def import_all_sources(
    database: WorkDatabase,
    manifest_path: Path,
    lock_path: Path,
    *,
    refresh_lock: bool = False,
) -> dict[str, int]:
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, list):
        raise ValueError("来源 manifest 必须是数组")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    cache_root = lock_path.parent / "downloads"
    cache_root.mkdir(parents=True, exist_ok=True)
    expanded = list(_expanded_sources(manifest))
    _validate_expanded_sources(expanded, cache_root)
    lock_payload = _read_lock_payload(lock_path)
    existing = {str(entry["key"]): entry for entry in lock_payload.get("sources", [])}
    if existing and not refresh_lock:
        locked_manifest = lock_payload.get("manifest_sha256")
        if locked_manifest != manifest_sha256:
            raise ValueError("来源 manifest 已漂移；如需更新必须显式使用 --refresh-lock")
    if refresh_lock and existing and set(existing) != {str(row["key"]) for row in expanded}:
        raise ValueError("refresh-lock 不允许增删来源 key，避免遗留 stale raw")
    locked: list[dict[str, Any]] = []
    imported: Counter[str] = Counter()

    for source in expanded:
        key = _required_string(source, "key")
        kind = _required_string(source, "kind")
        url = _source_url(source)
        cache_path = cache_root / _cache_filename(key, url)
        fingerprint = _config_fingerprint(source, url)
        previous = existing.get(key)
        changed = previous is not None and previous.get("config_fingerprint") != fingerprint
        compatible_migration = bool(
            previous and _legacy_lock_compatible(previous, kind, url, source)
        )
        if changed and not refresh_lock:
            raise ValueError(f"冻结来源配置已漂移: {key}")
        requires_refresh = bool(changed and refresh_lock and not compatible_migration)
        if requires_refresh and previous:
            old_identity = _locked_raw_source_name(previous)
            new_identity = _raw_source_name(source)
            if old_identity != new_identity:
                raise ValueError(
                    f"refresh-lock 禁止改变来源 identity: {old_identity} -> {new_identity}"
                )
        entry = _download_locked(
            key,
            kind,
            url,
            cache_path,
            previous,
            source=source,
            refresh=requires_refresh,
        )
        entry["config_fingerprint"] = fingerprint
        entry["config"] = _source_config(source, url)
        if requires_refresh:
            database.delete_raw_source(_raw_source_name(source))
        locked.append(entry)
        _checkpoint_source_lock(
            lock_path, manifest_path, manifest_sha256, locked, existing, complete=False
        )
        items = _iter_source(kind, cache_path, source)
        imported[kind] += _import_items(database, items, source.get("max_items"))

    _checkpoint_source_lock(
        lock_path, manifest_path, manifest_sha256, locked, {}, complete=True
    )
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
    if payload.get("version") != _LOCK_VERSION or not payload.get("manifest_sha256"):
        raise ValueError("source lock 版本过旧或缺少 manifest SHA-256")
    for entry in payload.get("sources", []):
        cache_path = (lock_path.parent / str(entry["cache_path"])).resolve()
        downloads = (lock_path.parent / "downloads").resolve()
        if not cache_path.is_relative_to(downloads):
            raise ValueError(f"冻结来源缓存越界: {cache_path}")
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
    *,
    source: dict[str, Any],
    refresh: bool,
) -> dict[str, Any]:
    if existing and cache_path.is_file():
        size, digest = _file_fingerprint(cache_path)
        if not refresh and size == existing.get("size_bytes") and digest == existing.get("sha256"):
            return dict(existing)
    temporary = cache_path.with_suffix(cache_path.suffix + ".part")
    if kind != "wikinews":
        temporary.unlink(missing_ok=True)
    if kind == "wikinews" and url.startswith(("http://", "https://")):
        final_url = _download_wikinews_snapshot(url, temporary, source)
    else:
        final_url = _download_url(url, temporary)
    size, digest = _file_fingerprint(temporary)
    if existing and not refresh and (
        size != existing.get("size_bytes") or digest != existing.get("sha256")
    ):
        temporary.unlink(missing_ok=True)
        raise ValueError(f"上游来源字节已变化，拒绝覆盖冻结缓存: {key}")
    temporary.replace(cache_path)
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


def _download_url(url: str, target_path: Path) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "listening-cloze/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response, target_path.open("wb") as target:
        while chunk := response.read(1024 * 1024):
            target.write(chunk)
        return response.geturl()


def _download_wikinews_snapshot(url: str, target_path: Path, source: dict[str, Any]) -> str:
    base_url = url.split("?", 1)[0]
    article_limit = int(source.get("article_limit", 2000))
    batch_size = int(source.get("batch_size", 20))
    pages: dict[int, dict[str, Any]] = {}
    scanned_page_ids: set[int] = set()
    continuation: dict[str, str] = {}
    if target_path.is_file():
        checkpoint = json.loads(target_path.read_text(encoding="utf-8"))
        if checkpoint.get("checkpoint_version") == 1:
            pages = {int(page["pageid"]): page for page in checkpoint.get("pages", [])}
            scanned_page_ids = {int(value) for value in checkpoint.get("scanned_page_ids", [])}
            continuation = {
                str(key): str(value) for key, value in checkpoint.get("continuation", {}).items()
            }
    while len(scanned_page_ids) < article_limit:
        query = _WIKINEWS_QUERY | {
            "gcmlimit": str(batch_size),
            "exlimit": str(batch_size),
        } | continuation
        request_url = f"{base_url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            request_url, headers={"User-Agent": "listening-cloze/0.1"}
        )
        payload = _read_json_with_retries(request)
        for page in payload.get("query", {}).get("pages", []):
            page_id = page.get("pageid")
            if isinstance(page_id, int):
                scanned_page_ids.add(page_id)
                if page.get("extract"):
                    pages[page_id] = page
        next_values = payload.get("continue")
        if not isinstance(next_values, dict):
            break
        continuation = {str(key): str(value) for key, value in next_values.items()}
        _atomic_write_json(
            target_path,
            {
                "checkpoint_version": 1,
                "pages": [pages[key] for key in sorted(pages)],
                "scanned_page_ids": sorted(scanned_page_ids),
                "continuation": continuation,
            },
        )
        time.sleep(0.25)
    stable_pages = [pages[key] for key in sorted(pages)[:article_limit]]
    target_path.write_text(
        json.dumps({"query": {"pages": stable_pages}}, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return base_url


def _read_json_with_retries(request: urllib.request.Request) -> dict[str, Any]:
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ValueError("Wikinews API 响应不是对象")
            return payload
        except (urllib.error.HTTPError, urllib.error.URLError) as error:
            if isinstance(error, urllib.error.HTTPError) and error.code != 429:
                raise
            if attempt == 5:
                raise
            retry_after = error.headers.get("Retry-After") if hasattr(error, "headers") else None
            delay = float(retry_after) if retry_after else float(2 ** (attempt + 1))
            time.sleep(min(delay, 60.0))
    raise RuntimeError("Wikinews 重试循环意外结束")


def _iter_source(
    kind: str, cache_path: Path, source: dict[str, Any]
) -> Iterable[CollectedSentence]:
    if kind == "tatoeba":
        return iter_tatoeba_detailed(cache_path)
    if kind == "convokit":
        extracted = cache_path.parent / f"{cache_path.stem}-extracted"
        _ensure_convokit_extracted(cache_path, extracted)
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


def _ensure_convokit_extracted(archive_path: Path, output: Path) -> None:
    _, archive_sha = _file_fingerprint(archive_path)
    marker = output / "archive-sha256.txt"
    if (
        marker.is_file()
        and marker.read_text(encoding="utf-8").strip() == archive_sha
        and (output / "utterances.jsonl").is_file()
    ):
        return
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    backup = output.with_name(f".{output.name}-old")
    try:
        _extract_convokit(archive_path, temporary)
        (temporary / "archive-sha256.txt").write_text(archive_sha + "\n", encoding="utf-8")
        if backup.exists():
            shutil.rmtree(backup)
        if output.exists():
            os.replace(output, backup)
        os.replace(temporary, output)
        if backup.exists():
            shutil.rmtree(backup)
    except BaseException:
        if not output.exists() and backup.exists():
            os.replace(backup, output)
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


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


def _read_lock_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _checkpoint_source_lock(
    lock_path: Path,
    manifest_path: Path,
    manifest_sha256: str,
    locked: list[dict[str, Any]],
    existing: dict[str, dict[str, Any]],
    *,
    complete: bool,
) -> None:
    completed_keys = {str(entry["key"]) for entry in locked}
    sources = [
        *locked,
        *(entry for key, entry in existing.items() if key not in completed_keys),
    ]
    _atomic_write_json(
        lock_path,
        {
            "version": _LOCK_VERSION,
            "manifest": str(manifest_path),
            "manifest_sha256": manifest_sha256,
            "complete": complete,
            "sources": sources,
        },
    )


def _validate_expanded_sources(sources: list[dict[str, Any]], cache_root: Path) -> None:
    keys: set[str] = set()
    paths: set[Path] = set()
    root = cache_root.resolve()
    for source in sources:
        key = _required_string(source, "key")
        if not _SAFE_KEY.fullmatch(key):
            raise ValueError(f"来源 key 不是安全 slug: {key}")
        if key in keys:
            raise ValueError(f"来源 manifest 包含重复 expanded key: {key}")
        keys.add(key)
        url = _source_url(source)
        path = (cache_root / _cache_filename(key, url)).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"来源缓存路径越界: {path}")
        if path in paths:
            raise ValueError(f"来源 manifest 包含重复缓存路径: {path.name}")
        paths.add(path)


def _source_config(source: dict[str, Any], url: str) -> dict[str, Any]:
    return {
        "config_version": 2,
        "key": source["key"],
        "kind": source["kind"],
        "requested_url": url,
        "max_items": source.get("max_items"),
        "license_name": source.get("license_name"),
        "license_url": source.get("license_url"),
        "ebook_id": source.get("ebook_id"),
        "article_limit": source.get("article_limit"),
        "batch_size": source.get("batch_size"),
        "snapshot_version": source.get("snapshot_version"),
    }


def _config_fingerprint(source: dict[str, Any], url: str) -> str:
    encoded = json.dumps(_source_config(source, url), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _legacy_lock_compatible(
    entry: dict[str, Any], kind: str, url: str, source: dict[str, Any]
) -> bool:
    if entry.get("config_fingerprint"):
        return False
    if entry.get("kind") != kind:
        return False
    if kind == "wikinews":
        return False
    return entry.get("requested_url") == url


def _raw_source_name(source: dict[str, Any]) -> str:
    kind = str(source["kind"])
    if kind == "tatoeba":
        return "Tatoeba"
    if kind == "wikinews":
        return "English Wikinews"
    if kind == "gutenberg":
        return "Project Gutenberg"
    return str(source["key"])


def _locked_raw_source_name(entry: dict[str, Any]) -> str:
    config = entry.get("config")
    if not isinstance(config, dict):
        return _raw_source_name({"kind": entry["kind"], "key": entry["key"]})
    return _raw_source_name(config)


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
