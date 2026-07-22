from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.content_pipeline import production_sources
from tools.content_pipeline.models import CollectedSentence


def _sentence(source_name: str) -> CollectedSentence:
    return CollectedSentence(
        text="A complete sentence for integration testing.",
        source_item_id="item-1",
        source_author="Tester",
        source_url="https://example.test/source",
        source_name=source_name,
        license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            {"kind": "taskmaster2", "key": "taskmaster2-movies", "domain": "movies"},
            "taskmaster2-movies",
        ),
        (
            {"kind": "taskmaster2", "key": "taskmaster2-sports", "domain": "sports"},
            "taskmaster2-sports",
        ),
        (
            {
                "kind": "stackexchange-api",
                "key": "stackexchange-api-workplace",
                "site": "workplace",
            },
            "stackexchange-workplace-official-api-snapshot",
        ),
        (
            {
                "kind": "stackexchange-api",
                "key": "stackexchange-api-academia",
                "site": "academia",
            },
            "stackexchange-academia-official-api-snapshot",
        ),
    ],
)
def test_targeted_source_identity_matches_parser_output(
    source: dict[str, str], expected: str
) -> None:
    assert production_sources._raw_source_name(source) == expected


@pytest.mark.parametrize("site", [" Workplace ", "Workplace", "unknown"])
def test_stackexchange_identity_rejects_noncanonical_site(site: str) -> None:
    with pytest.raises(ValueError, match="Stack Exchange site"):
        production_sources._raw_source_name(
            {"kind": "stackexchange", "key": "stackexchange-fixture", "site": site}
        )


@pytest.mark.parametrize(
    ("kind", "config_field", "config_value", "reader_name", "source_name"),
    [
        (
            "taskmaster2",
            "domain",
            "movies",
            "iter_taskmaster2_utterances",
            "taskmaster2-movies",
        ),
        (
            "stackexchange-api",
            "site",
            "workplace",
            "iter_stackexchange_api_sentences",
            "stackexchange-workplace-official-api-snapshot",
        ),
    ],
)
def test_targeted_source_dispatch_and_download_validation_use_fixed_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    config_field: str,
    config_value: str,
    reader_name: str,
    source_name: str,
) -> None:
    source_path = tmp_path / "source"
    expected = _sentence(source_name)
    calls: list[tuple[Path, str]] = []

    def reader(path: Path, **kwargs: str):
        calls.append((path, kwargs[config_field]))
        return iter([expected])

    monkeypatch.setattr(production_sources, reader_name, reader)
    source = {
        "kind": kind,
        "key": f"{kind}-fixture",
        config_field: config_value,
    }

    assert list(production_sources._iter_source(kind, source_path, source)) == [expected]
    production_sources._validate_downloaded_source(kind, source_path, source, "0" * 64)

    assert calls == [(source_path, config_value), (source_path, config_value)]


@pytest.mark.parametrize(
    ("kind", "field", "first", "second"),
    [
        ("taskmaster2", "domain", "movies", "sports"),
        ("stackexchange-api", "site", "workplace", "academia"),
    ],
)
def test_targeted_source_mapping_is_frozen_in_config_fingerprint(
    kind: str, field: str, first: str, second: str
) -> None:
    source = {
        "key": f"{kind}-fixture",
        "kind": kind,
        "url": "https://example.test/source",
        field: first,
        "schema_version": 1,
    }
    config = production_sources._source_config(source, source["url"])
    before = production_sources._config_fingerprint(source, source["url"])

    assert config[field] == first
    assert config["schema_version"] == 1
    source[field] = second
    assert production_sources._config_fingerprint(source, source["url"]) != before


@pytest.mark.parametrize(
    ("source_name", "expected"),
    [
        ("taskmaster2-movies", "taskmaster2"),
        ("taskmaster2-sports", "taskmaster2"),
        ("stackexchange-workplace-official-dump", "stackexchange"),
        ("stackexchange-fitness-official-dump", "stackexchange"),
        ("stackexchange-workplace-official-api-snapshot", "stackexchange-api"),
        ("stackexchange-academia-official-api-snapshot", "stackexchange-api"),
    ],
)
def test_targeted_source_report_collapses_fixed_variants(
    source_name: str, expected: str
) -> None:
    assert production_sources._source_kind(source_name) == expected


def test_expected_hash_allows_reusing_a_preseeded_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "downloads" / "taskmaster2-movies.json"
    cache_path.parent.mkdir()
    cache_path.write_text(
        json.dumps(
            [
                {
                    "conversation_id": "movie-1",
                    "instruction_id": "movie-default",
                    "utterances": [
                        {
                            "index": 0,
                            "speaker": "USER",
                            "text": "Please recommend a movie.",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(cache_path.read_bytes()).hexdigest()
    source = {
        "key": "taskmaster2-movies",
        "kind": "taskmaster2",
        "domain": "movies",
        "expected_sha256": digest,
    }

    def fail_download(_url: str, _target: Path) -> str:
        raise AssertionError("命中预期哈希的预置缓存不应再次下载")

    monkeypatch.setattr(production_sources, "_download_url", fail_download)

    entry = production_sources._download_locked(
        "taskmaster2-movies",
        "taskmaster2",
        "https://example.test/movies.json",
        cache_path,
        None,
        source=source,
        refresh=False,
    )

    assert entry["sha256"] == digest
    assert entry["size_bytes"] == cache_path.stat().st_size
    assert entry["cache_path"] == "downloads/taskmaster2-movies.json"


def test_manifest_freezes_taskmaster_and_stackexchange_sources() -> None:
    manifest_path = Path(__file__).parents[2] / "tools/content_pipeline/source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_key = {str(source["key"]): source for source in manifest}

    assert by_key["taskmaster2-movies"] == {
        "key": "taskmaster2-movies",
        "kind": "taskmaster2",
        "domain": "movies",
        "schema_version": 1,
        "url": (
            "https://raw.githubusercontent.com/google-research-datasets/Taskmaster/"
            "d92cb6af3005f1dc09c39e75e7daf4a04905e00b/TM-2-2020/data/movies.json"
        ),
        "expected_sha256": "6f67c9a1f04abc111186e5bcfbe3050be01d0737fd6422901402715bc1f3dd0d",
        "max_items": 10000,
        "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
    }
    assert by_key["taskmaster2-sports"] == {
        "key": "taskmaster2-sports",
        "kind": "taskmaster2",
        "domain": "sports",
        "schema_version": 1,
        "url": (
            "https://raw.githubusercontent.com/google-research-datasets/Taskmaster/"
            "d92cb6af3005f1dc09c39e75e7daf4a04905e00b/TM-2-2020/data/sports.json"
        ),
        "expected_sha256": "8191531bfa5a8426b1508c396ab9886a19c7c620b443c436ec10d8d4708d0eac",
        "max_items": 10000,
        "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
    }

    expected_api_snapshots = {
        "workplace": (
            "e2994240647fc9e38aa78f5e1052eebbcb386fdc7da2b75113d4a651e0691da0"
        ),
        "academia": (
            "0908dcf456e08036da9b08fc6cca111c43001ac47dba055df4dab01beefc03be"
        ),
        "softwareengineering": (
            "6a01a9d0e046a017ba3d8c70aa22830c4e61159e8ca4c8e822455e60e6588bf7"
        ),
    }
    for site, expected_sha256 in expected_api_snapshots.items():
        assert by_key[f"stackexchange-api-{site}"] == {
            "key": f"stackexchange-api-{site}",
            "kind": "stackexchange-api",
            "site": site,
            "schema_version": 1,
            "bundled_path": f"snapshots/stackexchange-{site}-api-v1.json",
            "expected_sha256": expected_sha256,
            "max_items": 15000,
            "license_name": "per-item CC BY-SA",
            "license_url": "https://stackoverflow.com/help/licensing",
        }
    assert by_key["stackexchange-fitness"] == {
        "key": "stackexchange-fitness",
        "kind": "stackexchange",
        "site": "fitness",
        "schema_version": 1,
        "url": "https://archive.org/download/stackexchange/fitness.stackexchange.com.7z",
        "expected_sha256": "5fe08b64b0fbdc917aa66217af5d162270a59159eccd2fff8bc287674d4f52a7",
        "max_items": 15000,
        "license_name": "per-item CC BY-SA",
        "license_url": "https://stackoverflow.com/help/licensing",
    }


def test_bundled_snapshot_url_and_config_are_portable() -> None:
    source = {
        "key": "stackexchange-api-workplace",
        "kind": "stackexchange-api",
        "site": "workplace",
        "bundled_path": "snapshots/stackexchange-workplace-api-v1.json",
    }

    url = production_sources._source_url(source)
    config = production_sources._source_config(source, url)

    assert url == "bundled://snapshots/stackexchange-workplace-api-v1.json"
    assert config["bundled_path"] == source["bundled_path"]


@pytest.mark.parametrize(
    "bundled_path",
    ["../source_manifest.json", "/tmp/source.json", "snapshots/missing.json"],
)
def test_bundled_snapshot_rejects_unsafe_or_missing_path(bundled_path: str) -> None:
    source = {
        "key": "stackexchange-api-workplace",
        "kind": "stackexchange-api",
        "site": "workplace",
        "bundled_path": bundled_path,
    }

    with pytest.raises(ValueError, match="bundled_path"):
        production_sources._source_url(source)
