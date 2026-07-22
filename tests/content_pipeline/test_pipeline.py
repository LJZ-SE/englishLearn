from __future__ import annotations

import bz2
import json
import sqlite3
from pathlib import Path

import pytest

from tools.content_pipeline.builder import BuildError, build_database
from tools.content_pipeline.candidates import generate_variants
from tools.content_pipeline.categorize import CategoryClassifier, SceneClassifier
from tools.content_pipeline.clean import clean_sentence, normalized_hash, rejection_reason
from tools.content_pipeline.collector import SourceConfig, collect_sources, load_source_configs
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.selection import curate_balanced, curate_category, is_near_duplicate
from tools.content_pipeline.snapshot import load_snapshot, write_snapshot
from tools.content_pipeline.tatoeba import iter_tatoeba_detailed
from tools.content_pipeline.wikinews import iter_wikinews_extracts


def sentence(text: str, *, category: str | None = None) -> CollectedSentence:
    return CollectedSentence(
        text=text,
        source_url="https://example.test/source",
        source_name="Open Example",
        license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        category_hint=category,
        source_author="Example Author",
    )


def alphabetic_marker(index: int) -> str:
    first = chr(ord("a") + index // 26)
    second = chr(ord("a") + index % 26)
    return f"lexeme{first}{second} topic{second}{first} detail{first}{second}"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  <p>I\u00a0can’t   wait&nbsp;to begin!</p>  ", "I can't wait to begin!"),
        ("\ufeffThe “quick” fox\u200b jumps.\n", 'The "quick" fox jumps.'),
    ],
)
def test_clean_sentence_normalizes_html_unicode_quotes_and_whitespace(
    raw: str, expected: str
) -> None:
    assert clean_sentence(raw) == expected


def test_normalized_hash_deduplicates_case_spacing_and_curly_quotes() -> None:
    first = normalized_hash("Don’t stop now!")
    second = normalized_hash("  DON'T   STOP NOW! ")

    assert first == second


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("I was unhappy, but I would never kill myself.", "sensitive"),
        ("I opened the window. Then I called my neighbor.", "multiple_sentences"),
        ('What did the professor say? "The professor discussed the moon."', "multiple_sentences"),
        ("The speaker used a fucking insult during the angry exchange.", "sensitive"),
        ("The attack killed several people during the violent conflict.", "sensitive"),
        ("The soldiers were attacked during the war.", "sensitive"),
        ('The minister said "this is the moment of truth.', "unbalanced_quotes"),
    ],
)
def test_quality_filter_rejects_sensitive_or_multi_sentence_records(text: str, reason: str) -> None:
    assert rejection_reason(text) == reason


def test_classifier_honors_hint_then_uses_deterministic_keyword_scores() -> None:
    classifier = CategoryClassifier()

    assert classifier.classify(sentence("Stocks rallied after the central bank announcement.")) == (
        "news_podcasts"
    )
    assert classifier.classify(sentence("Please put the clean dishes in the cupboard.")) == "daily"
    assert classifier.classify(sentence("The hypothesis requires additional evidence.")) == "exam"
    movie_sentence = sentence("The film director asked the actor to repeat the final scene.")
    assert classifier.classify(movie_sentence) == "movies"
    assert classifier.classify(sentence("Neutral text.", category="exam")) == "exam"


@pytest.mark.parametrize(
    "text",
    [
        "My phone screen cracked while I was cooking dinner.",
        "Her generous character made every visitor feel welcome.",
        "I bought a small camera before leaving for vacation.",
    ],
)
def test_classifier_does_not_treat_ambiguous_media_words_as_movies(text: str) -> None:
    assert CategoryClassifier().classify(sentence(text)) == "daily"


def test_classifier_handles_plural_news_terms_and_open_news_provenance() -> None:
    classifier = CategoryClassifier()
    newspapers = sentence("Local newspapers reported the economic changes this morning.")
    voa = CollectedSentence(
        text="Farmers are learning how to protect their crops during dry seasons.",
        source_url="https://tatoeba.org/en/sentences/show/680734",
        source_name="Tatoeba",
        license_name="CC BY 2.0 FR",
        license_url="https://creativecommons.org/licenses/by/2.0/fr/",
        source_author="Source_VOA",
    )

    assert classifier.classify(newspapers) == "news_podcasts"
    assert classifier.classify(voa) == "news_podcasts"


def test_scene_classifier_honors_valid_source_scene_before_keyword_scoring() -> None:
    item = sentence("The hotel reservation was confirmed.")
    item = CollectedSentence(
        **{
            field: getattr(item, field)
            for field in (
                "text",
                "source_url",
                "source_name",
                "license_name",
                "license_url",
                "category_hint",
                "source_author",
            )
        },
        top_scene="work",
        sub_scene="work_office",
    )

    result = SceneClassifier().classify(item)

    assert (result.top_scene, result.sub_scene, result.method) == (
        "work",
        "work_office",
        "source_explicit",
    )


def test_generate_variants_returns_three_distinct_exact_spans_with_increasing_scores() -> None:
    original = "We should take part in the community meeting tomorrow evening."

    variants = generate_variants(original)

    assert [item.difficulty for item in variants] == ["easy", "medium", "hard"]
    assert len({item.canonical_answer.casefold() for item in variants}) == 3
    assert variants[0].score < variants[1].score < variants[2].score
    for item in variants:
        assert original[item.answer_start : item.answer_end] == item.canonical_answer
        assert item.blank_count == len(item.canonical_answer.split())
        rebuilt = (
            original[: item.answer_start] + item.canonical_answer + original[item.answer_end :]
        )
        assert rebuilt == original
    assert any(item.blank_count > 1 for item in variants)


def test_generate_variants_adds_common_contraction_aliases() -> None:
    variants = generate_variants("I do not think we can finish the difficult assignment tonight.")

    alias_pairs = {
        (item.canonical_answer.casefold(), alias.casefold())
        for item in variants
        for alias in item.aliases
    }
    assert ("do not", "don't") in alias_pairs or ("can", "cannot") in alias_pairs


def test_phrase_candidates_never_span_more_than_four_space_delimited_words() -> None:
    variants = generate_variants(
        "Officials expected costs of about $395 billion over the following decade."
    )

    assert all(1 <= item.blank_count <= 4 for item in variants)


def test_variants_avoid_auxiliary_only_words_and_unnatural_phrase_edges() -> None:
    variants = generate_variants(
        "The weather today is a bit better than yesterday because conditions improved."
    )
    unnatural_starters = {"is", "to", "of", "in", "i", "we", "you"}
    unnatural_endings = {"the", "is", "a", "to", "of", "in", "that"}

    assert all(
        item.canonical_answer.casefold() not in {"is", "should", "have"} for item in variants
    )
    for item in variants:
        words = item.canonical_answer.casefold().split()
        if len(words) > 1:
            assert words[0] not in unnatural_starters
            assert words[-1] not in unnatural_endings


def test_collector_reads_json_records_and_preserves_source_license_metadata(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "sentences.json"
    payload.write_text(
        json.dumps(
            [
                {
                    "text": "The train arrives at nine o'clock.",
                    "url": "https://primary.example/items/42",
                }
            ]
        ),
        encoding="utf-8",
    )
    source = SourceConfig(
        name="Primary Example",
        url=payload.as_uri(),
        format="json",
        text_field="text",
        item_url_field="url",
        license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        category_hint="daily",
    )

    collected = collect_sources([source])

    assert collected == [
        CollectedSentence(
            text="The train arrives at nine o'clock.",
            source_url="https://primary.example/items/42",
            source_name="Primary Example",
            license_name="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            category_hint="daily",
            source_author="",
        )
    ]


def test_collector_supports_headerless_tsv_attribution_category_and_item_url(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "sentences.tsv"
    payload.write_text(
        "42\teng\tWe always look after our neighbors during a storm.\talice\tdaily\n",
        encoding="utf-8",
    )
    source = SourceConfig(
        name="Open Corpus",
        url=payload.as_uri(),
        format="tsv",
        text_field="text",
        item_url_template="https://primary.example/sentences/{id}",
        license_name="CC BY 2.0",
        license_url="https://creativecommons.org/licenses/by/2.0/",
        field_names=("id", "language", "text", "author", "category"),
        author_field="author",
        category_field="category",
    )

    assert collect_sources([source]) == [
        CollectedSentence(
            text="We always look after our neighbors during a storm.",
            source_url="https://primary.example/sentences/42",
            source_name="Open Corpus",
            license_name="CC BY 2.0",
            license_url="https://creativecommons.org/licenses/by/2.0/",
            category_hint="daily",
            source_author="alice",
        )
    ]


def test_source_configs_load_from_json_and_convert_field_names_to_tuple(tmp_path: Path) -> None:
    config_path = tmp_path / "sources-config.json"
    config_path.write_text(
        json.dumps(
            [
                {
                    "name": "Tatoeba",
                    "url": "https://downloads.example/eng.tsv.bz2",
                    "format": "tsv",
                    "license_name": "CC BY 2.0 FR",
                    "license_url": "https://creativecommons.org/licenses/by/2.0/fr/",
                    "field_names": ["id", "language", "text", "author"],
                }
            ]
        ),
        encoding="utf-8",
    )

    configs = load_source_configs(config_path)

    assert len(configs) == 1
    assert configs[0].field_names == ("id", "language", "text", "author")


def test_curated_snapshot_round_trip_preserves_attribution(tmp_path: Path) -> None:
    items = [sentence("We always look after our neighbors during a storm.", category="daily")]
    snapshot = tmp_path / "snapshot.json"

    write_snapshot(items, snapshot)

    assert load_snapshot(snapshot) == items


def test_tatoeba_detailed_reader_maps_id_text_and_author_to_attributed_items(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "eng.tsv.bz2"
    with bz2.open(archive, "wt", encoding="utf-8") as stream:
        stream.write(
            "42\teng\tWe always look after our neighbors during a storm.\talice\t\\N\t2026-01-01\n"
        )

    assert list(iter_tatoeba_detailed(archive)) == [
        CollectedSentence(
            text="We always look after our neighbors during a storm.",
            source_url="https://tatoeba.org/en/sentences/show/42",
            source_name="Tatoeba",
            license_name="CC BY 2.0 FR",
            license_url="https://creativecommons.org/licenses/by/2.0/fr/",
            source_author="alice",
            source_item_id="42",
        )
    ]


def test_wikinews_reader_splits_article_intro_and_keeps_article_attribution(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "wikinews.json"
    payload.write_text(
        json.dumps(
            {
                "query": {
                    "pages": [
                        {
                            "title": "Council approves new rail plan",
                            "fullurl": "https://en.wikinews.org/wiki/Council_approves_new_rail_plan",
                            "extract": (
                                "Tuesday, July 21, 2026\n\n"
                                "The city council approved a new rail plan on Monday. "
                                "Officials said construction would begin next spring. "
                                "Residents can review the proposal on the council website."
                            ),
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    items = list(iter_wikinews_extracts(payload, max_per_article=2))

    assert [item.text for item in items] == [
        "The city council approved a new rail plan on Monday.",
        "Officials said construction would begin next spring.",
    ]
    assert all(item.category_hint == "news_podcasts" for item in items)
    assert all(item.source_author == "Wikinews" for item in items)
    assert [item.source_item_id for item in items] == [
        "Council approves new rail plan:1",
        "Council approves new rail plan:2",
    ]
    assert all(item.license_name == "CC BY 4.0" for item in items)


def test_wikinews_reader_assigns_license_from_publication_date(tmp_path: Path) -> None:
    payload = tmp_path / "wikinews-licenses.json"
    payload.write_text(
        json.dumps(
            {
                "query": {
                    "pages": [
                        {
                            "fullurl": "https://en.wikinews.org/wiki/Old_article",
                            "extract": (
                                "Monday, January 3, 2005\n\n"
                                "Officials presented the regional transport plan to residents."
                            ),
                        },
                        {
                            "fullurl": "https://en.wikinews.org/wiki/Later_article",
                            "extract": (
                                "Tuesday, January 3, 2006\n\n"
                                "Officials presented a different transport plan to residents."
                            ),
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    items = list(iter_wikinews_extracts(payload))

    assert [(item.license_name, item.license_url) for item in items] == [
        ("Public domain", "https://creativecommons.org/publicdomain/mark/1.0/"),
        ("CC BY 2.5", "https://creativecommons.org/licenses/by/2.5/"),
    ]


def test_wikinews_reader_does_not_split_titles_or_initials(tmp_path: Path) -> None:
    payload = tmp_path / "wikinews-titles.json"
    payload.write_text(
        json.dumps(
            {
                "query": {
                    "pages": [
                        {
                            "fullurl": "https://en.wikinews.org/wiki/Research_update",
                            "extract": (
                                "Monday, July 20, 2026\n\n"
                                "Dr. Smith presented the results to reporters. "
                                "The U.K. research team plans another experiment."
                            ),
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert [item.text for item in iter_wikinews_extracts(payload)] == [
        "Dr. Smith presented the results to reporters.",
        "The U.K. research team plans another experiment.",
    ]


def test_near_duplicate_detection_rejects_minor_rewording_but_keeps_distinct_sentences() -> None:
    original = "The committee will review the detailed proposal during tomorrow's meeting."

    assert is_near_duplicate(
        original,
        "The committee will review the detailed proposal during the meeting tomorrow.",
    )
    assert not is_near_duplicate(
        original,
        "My sister packed a warm jacket before walking to the station.",
    )


def test_curate_balanced_uses_automatic_categories_and_stops_at_exact_quota() -> None:
    candidates = [
        sentence("Please put the clean dishes back in the kitchen cupboard."),
        sentence("The research evidence supports the student's original hypothesis."),
        sentence("The film director asked the actor to repeat the final scene."),
        sentence("The government announced a new economic policy during the broadcast."),
        sentence("We usually buy fresh bread after work on Friday evening."),
    ]

    selected = curate_balanced(candidates, quota=1)

    classifier = CategoryClassifier()
    assert len(selected) == 4
    assert {classifier.classify(item) for item in selected} == {
        "daily",
        "exam",
        "movies",
        "news_podcasts",
    }


def test_curate_balanced_is_independent_of_download_order() -> None:
    candidates = [
        sentence("Please put the clean dishes back in the kitchen cupboard."),
        sentence("We buy fresh vegetables at the local market every weekend."),
        sentence("The research evidence supports the student's original hypothesis."),
        sentence("Her academic essay offered a careful analysis of the evidence."),
        sentence("The film director asked the actor to repeat the final scene."),
        sentence("The actress enjoyed reading the documentary script before filming."),
        sentence("The government announced a new economic policy during the broadcast."),
        sentence("The journalist interviewed the president after the official vote."),
    ]

    forward = curate_balanced(candidates, quota=1)
    backward = curate_balanced(reversed(candidates), quota=1)

    assert [item.text for item in forward] == [item.text for item in backward]


def test_curate_single_category_is_deterministic_and_exact() -> None:
    candidates = [
        sentence(text, category="news_podcasts")
        for text in (
            "Officials released a detailed public report about the regional rail project.",
            "Journalists interviewed the mayor after the council approved its annual budget.",
            "The weather service issued a forecast for heavy rain along the coast.",
            "Researchers shared new findings about solar energy during a public conference.",
        )
    ]

    forward = curate_category(candidates, category="news_podcasts", quota=2)
    backward = curate_category(reversed(candidates), category="news_podcasts", quota=2)

    assert len(forward) == 2
    assert [item.text for item in forward] == [item.text for item in backward]


def test_build_database_writes_exact_balanced_counts_and_quality_artifacts(
    tmp_path: Path,
) -> None:
    inputs: list[CollectedSentence] = []
    for category_index, category in enumerate(("daily", "exam", "movies", "news_podcasts")):
        for index in range(75):
            marker = alphabetic_marker(category_index * 75 + index)
            inputs.append(
                sentence(
                    f"Careful learners take part in a practical {category} exercise "
                    f"about {marker} today.",
                    category=category,
                )
            )

    database = tmp_path / "content.db"
    report = tmp_path / "quality-report.json"
    sources = tmp_path / "sources.json"
    result = build_database(inputs, database, report, sources)

    assert result.sentence_count == 300
    assert result.variant_count == 900
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sentences").fetchone()[0] == 300
        assert connection.execute("SELECT COUNT(*) FROM question_variants").fetchone()[0] == 900
        assert dict(
            connection.execute(
                "SELECT category, COUNT(*) FROM sentences GROUP BY category ORDER BY category"
            )
        ) == {"daily": 75, "exam": 75, "movies": 75, "news_podcasts": 75}
        bad_spans = connection.execute(
            """
            SELECT COUNT(*)
            FROM question_variants AS q
            JOIN sentences AS s ON s.id = q.sentence_id
            WHERE substr(s.text, q.answer_start + 1, q.answer_end - q.answer_start)
                  != q.canonical_answer
               OR q.answer_word_count != length(trim(q.canonical_answer))
                    - length(replace(trim(q.canonical_answer), ' ', '')) + 1
            """
        ).fetchone()[0]
    assert bad_spans == 0
    assert json.loads(report.read_text(encoding="utf-8"))["gate_status"] == "passed"
    source_manifest = json.loads(sources.read_text(encoding="utf-8"))
    assert source_manifest[0]["source_url"] == "https://example.test/source"
    assert source_manifest[0]["license_name"] == "CC BY 4.0"


def test_build_database_rejects_duplicate_or_unbalanced_input(tmp_path: Path) -> None:
    duplicated = [sentence("We take part in the same useful meeting.", category="daily")] * 300

    with pytest.raises(BuildError, match="每类 75"):
        build_database(
            duplicated,
            tmp_path / "content.db",
            tmp_path / "report.json",
            tmp_path / "sources.json",
        )
