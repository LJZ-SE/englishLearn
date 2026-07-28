from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "tools" / "assets" / "ecdict_assets.json"
DEFAULT_DESTINATION = ROOT / "src" / "listening_cloze" / "data" / "ecdict"
FIELDS = (
    "word",
    "phonetic",
    "definition",
    "translation",
    "pos",
    "collins",
    "oxford",
    "tag",
    "bnc",
    "frq",
    "exchange",
    "detail",
    "audio",
)


@dataclass(frozen=True, slots=True)
class EcdictManifest:
    repository: str
    revision: str
    csv_path: str
    csv_sha256: str
    license_path: str
    license_sha256: str
    expected_row_count: int


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> EcdictManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    manifest = EcdictManifest(
        repository=str(payload["repository"]),
        revision=str(payload["revision"]),
        csv_path=str(payload["csv_path"]),
        csv_sha256=str(payload["csv_sha256"]),
        license_path=str(payload["license_path"]),
        license_sha256=str(payload["license_sha256"]),
        expected_row_count=int(payload["expected_row_count"]),
    )
    if re.fullmatch(r"[0-9a-f]{40}", manifest.revision) is None:
        raise ValueError("ECDICT 资源必须固定到完整的提交 SHA")
    for value in (manifest.csv_sha256, manifest.license_sha256):
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("ECDICT 资源必须提供有效的 SHA-256")
    if manifest.expected_row_count <= 0:
        raise ValueError("ECDICT 词条数量必须为正整数")
    return manifest


def source_url(manifest: EcdictManifest, relative_path: str) -> str:
    return (
        f"https://raw.githubusercontent.com/{manifest.repository}/"
        f"{manifest.revision}/{relative_path}"
    )


def _download(url: str, destination: Path, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "ListeningClozeBuilder/1"})
    with urllib.request.urlopen(request, timeout=180) as source, destination.open("wb") as target:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            target.write(chunk)
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"ECDICT 下载文件哈希不匹配：{actual}")


def _integer(row: dict[str, str], field: str) -> int:
    try:
        return int(row.get(field) or 0)
    except ValueError:
        return 0


def _entry_values(row: dict[str, str]) -> tuple[str | int, ...]:
    return (
        row.get("word") or "",
        row.get("phonetic") or "",
        row.get("definition") or "",
        row.get("translation") or "",
        row.get("pos") or "",
        _integer(row, "collins"),
        _integer(row, "oxford"),
        row.get("tag") or "",
        _integer(row, "bnc"),
        _integer(row, "frq"),
        row.get("exchange") or "",
        row.get("detail") or "",
        row.get("audio") or "",
    )


def build_database(
    csv_path: str | Path,
    destination: str | Path,
    *,
    expected_row_count: int,
) -> int:
    source_path = Path(csv_path)
    output_path = Path(destination)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="dictionary-",
        suffix=".db",
        dir=output_path.parent,
        delete=False,
    ) as staged_file:
        staged_path = Path(staged_file.name)
    try:
        connection = sqlite3.connect(staged_path)
        try:
            connection.executescript(
                """
                PRAGMA journal_mode = OFF;
                PRAGMA synchronous = OFF;
                PRAGMA temp_store = MEMORY;
                PRAGMA page_size = 4096;

                CREATE TABLE entries (
                    id INTEGER PRIMARY KEY,
                    word TEXT NOT NULL,
                    phonetic TEXT NOT NULL DEFAULT '',
                    definition TEXT NOT NULL DEFAULT '',
                    translation TEXT NOT NULL DEFAULT '',
                    pos TEXT NOT NULL DEFAULT '',
                    collins INTEGER NOT NULL DEFAULT 0,
                    oxford INTEGER NOT NULL DEFAULT 0,
                    tag TEXT NOT NULL DEFAULT '',
                    bnc INTEGER NOT NULL DEFAULT 0,
                    frq INTEGER NOT NULL DEFAULT 0,
                    exchange TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    audio TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX idx_entries_word ON entries(word COLLATE NOCASE);
                """
            )
            insert = """
                INSERT INTO entries (
                    word, phonetic, definition, translation, pos, collins, oxford,
                    tag, bnc, frq, exchange, detail, audio
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            count = 0
            batch: list[tuple[str | int, ...]] = []
            with source_path.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                if tuple(reader.fieldnames or ()) != FIELDS:
                    raise ValueError("ECDICT CSV 字段与固定数据契约不一致")
                for row in reader:
                    batch.append(_entry_values(row))
                    if len(batch) >= 10_000:
                        connection.executemany(insert, batch)
                        count += len(batch)
                        batch.clear()
                if batch:
                    connection.executemany(insert, batch)
                    count += len(batch)
            if count != expected_row_count:
                raise ValueError(
                    f"ECDICT 词条数量异常：应为 {expected_row_count}，实际为 {count}"
                )
            connection.execute("ANALYZE")
            connection.commit()
            connection.execute("VACUUM")
        finally:
            connection.close()
        os.replace(staged_path, output_path)
        return count
    finally:
        staged_path.unlink(missing_ok=True)


def _write_runtime_manifest(
    destination: Path,
    source_manifest: EcdictManifest,
    *,
    database_path: Path,
) -> None:
    digest = hashlib.sha256()
    with database_path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    payload = {
        "repository": source_manifest.repository,
        "revision": source_manifest.revision,
        "source_csv_sha256": source_manifest.csv_sha256,
        "database_sha256": digest.hexdigest(),
        "row_count": source_manifest.expected_row_count,
        "license": "MIT",
    }
    (destination / "asset-manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch(
    destination: str | Path = DEFAULT_DESTINATION,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> Path:
    manifest = load_manifest(manifest_path)
    destination_path = Path(destination)
    destination_path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ecdict-download-") as temporary:
        temporary_path = Path(temporary)
        csv_path = temporary_path / "ecdict.csv"
        license_path = temporary_path / "LICENSE"
        _download(
            source_url(manifest, manifest.csv_path),
            csv_path,
            manifest.csv_sha256,
        )
        _download(
            source_url(manifest, manifest.license_path),
            license_path,
            manifest.license_sha256,
        )
        database_path = destination_path / "dictionary.db"
        build_database(
            csv_path,
            database_path,
            expected_row_count=manifest.expected_row_count,
        )
        (destination_path / "LICENSE").write_bytes(license_path.read_bytes())
        _write_runtime_manifest(
            destination_path,
            manifest,
            database_path=database_path,
        )
    return destination_path / "dictionary.db"


def main() -> int:
    parser = argparse.ArgumentParser(description="下载、校验并构建完整 ECDICT 离线词典")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    arguments = parser.parse_args()
    database = fetch(arguments.destination, arguments.manifest)
    print(f"ECDICT 完整词典已生成：{database.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
