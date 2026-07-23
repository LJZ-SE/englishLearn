from __future__ import annotations

from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import (
    SCENES,
    SUB_SCENES,
    TOP_SCENES,
    TOTAL_SENTENCE_QUOTA,
    scene_by_key,
)


def test_scene_catalog_contains_exact_confirmed_hierarchy_and_quota() -> None:
    assert len({scene.top_key for scene in SCENES}) == 9
    assert len(SCENES) == 34
    assert TOTAL_SENTENCE_QUOTA == 36_000
    assert sum(scene.quota for scene in SCENES) == 36_000
    assert scene_by_key("daily_social").quota == 1_800
    assert scene_by_key("travel_hotel").top_key == "travel"
    assert scene_by_key("news_environment").label == "环境社会"
    assert scene_by_key("cet_cet4").quota == 3_000
    assert scene_by_key("cet_cet6").top_key == "cet"


def test_scene_catalog_derives_indexes_from_the_single_scene_directory() -> None:
    assert TOP_SCENES == (
        ("daily", "日常生活"),
        ("travel", "出行旅行"),
        ("work", "职场商务"),
        ("study", "学习考试"),
        ("health", "健康医疗"),
        ("technology", "科技科学"),
        ("culture", "文化娱乐"),
        ("news", "新闻社会"),
        ("cet", "四六级考试"),
    )
    assert tuple(SUB_SCENES.values()) == SCENES


def test_collected_sentence_keeps_new_scene_provenance_fields_backward_compatible() -> None:
    sentence = CollectedSentence(
        text="The train arrives at nine.",
        source_url="https://example.test/sentences/42",
        source_name="Example",
        license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
    )

    assert sentence.source_item_id == ""
    assert sentence.top_scene is None
    assert sentence.sub_scene is None
