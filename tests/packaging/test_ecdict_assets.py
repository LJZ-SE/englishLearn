from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tools.assets.fetch_ecdict import build_database, load_manifest


def _write_csv(path: Path) -> None:
    fields = (
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
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "word": "listen",
                "phonetic": "lisn",
                "definition": "give attention to sound",
                "translation": "听；倾听",
                "pos": "v:100",
                "collins": "4",
                "oxford": "1",
                "tag": "cet4",
                "bnc": "900",
                "frq": "700",
                "exchange": "p:listened",
                "detail": "",
                "audio": "",
            }
        )


def test_ecdict_builder_preserves_every_source_column(tmp_path: Path) -> None:
    csv_path = tmp_path / "ecdict.csv"
    destination = tmp_path / "dictionary.db"
    _write_csv(csv_path)

    row_count = build_database(csv_path, destination, expected_row_count=1)

    assert row_count == 1
    with sqlite3.connect(destination) as connection:
        row = connection.execute("SELECT * FROM entries").fetchone()
        columns = {
            item[1] for item in connection.execute("PRAGMA table_info(entries)").fetchall()
        }
        assert columns == {
            "id",
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
        }
        assert row[1] == "listen"
        assert row[4] == "听；倾听"


def test_ecdict_builder_rejects_incomplete_source(tmp_path: Path) -> None:
    csv_path = tmp_path / "ecdict.csv"
    _write_csv(csv_path)

    with pytest.raises(ValueError, match="词条数量"):
        build_database(csv_path, tmp_path / "dictionary.db", expected_row_count=2)


def test_ecdict_manifest_requires_pinned_revision_and_hashes(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "repository": "skywind3000/ECDICT",
                "revision": "main",
                "csv_path": "ecdict.csv",
                "csv_sha256": hashlib.sha256(b"csv").hexdigest(),
                "license_path": "LICENSE",
                "license_sha256": hashlib.sha256(b"license").hexdigest(),
                "expected_row_count": 770611,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="提交 SHA"):
        load_manifest(manifest_path)
