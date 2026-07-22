from __future__ import annotations

import pytest

from tools.content_pipeline import builder
from tools.content_pipeline.builder import BuildError


def _row(
    *,
    scene: str = "daily_social",
    source_url: str = "https://example.test/source",
    author: str = "",
    license_name: str = "CC BY 4.0",
    license_url: str = "https://creativecommons.org/licenses/by/4.0/",
) -> tuple[str, str, str, str, str]:
    return scene, source_url, author, license_name, license_url


def test_release_provenance_allows_blank_authors_and_caps_only_named_authors() -> None:
    rows = [_row() for _ in range(19)] + [_row(author="Named Author")]

    builder._validate_release_provenance(rows)

    with pytest.raises(BuildError, match="作者占比"):
        builder._validate_release_provenance(rows + [_row(author="Named Author")])


def test_release_provenance_rejects_scene_overage_even_when_global_share_is_low() -> None:
    small_scene = [
        _row(scene="daily_social", author="Named Author" if index < 2 else "")
        for index in range(20)
    ]
    large_scene = [_row(scene="travel_hotel") for _ in range(80)]

    with pytest.raises(BuildError, match="daily_social.*作者占比"):
        builder._validate_release_provenance(small_scene + large_scene)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source_url": ""}, "来源 URL"),
        ({"source_url": "http://example.test/source"}, "来源 URL"),
        ({"license_name": ""}, "许可证名称"),
        ({"license_url": ""}, "许可证 URL"),
        ({"license_url": "http://example.test/license"}, "许可证 URL"),
    ],
)
def test_release_provenance_requires_https_source_and_license_urls(
    overrides: dict[str, str], message: str
) -> None:
    with pytest.raises(BuildError, match=message):
        builder._validate_release_provenance([_row(**overrides)])
