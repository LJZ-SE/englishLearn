from __future__ import annotations

import bz2
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import tools.content_pipeline.builder as builder
from tools.content_pipeline.builder import BuildError, build_database
from tools.content_pipeline.candidates import generate_variants
from tools.content_pipeline.categorize import CategoryClassifier, SceneClassifier
from tools.content_pipeline.clean import clean_sentence, normalized_hash, rejection_reason
from tools.content_pipeline.collector import SourceConfig, collect_sources, load_source_configs
from tools.content_pipeline.models import BuildResult, CollectedSentence
from tools.content_pipeline.scenes import SCENES
from tools.content_pipeline.selection import curate_balanced, curate_category, is_near_duplicate
from tools.content_pipeline.snapshot import load_snapshot, write_snapshot
from tools.content_pipeline.tatoeba import iter_tatoeba_detailed
from tools.content_pipeline.wikinews import iter_wikinews_extracts
from tools.content_pipeline.work_database import WorkDatabase


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


def _variant_payload(text: str) -> dict[str, object]:
    return {
        "variants": [
            {
                "difficulty": variant.difficulty,
                "answer_start": variant.answer_start,
                "answer_end": variant.answer_end,
                "canonical_answer": variant.canonical_answer,
                "answer_word_count": variant.blank_count,
                "difficulty_score": variant.score,
                "rationale": variant.rationale,
                "aliases": list(variant.aliases),
            }
            for variant in generate_variants(text)
        ]
    }


def build_fixture_database(
    tmp_path: Path,
    *,
    per_scene: int = 1,
    preserve_ids_from: Path | None = None,
) -> BuildResult:
    tmp_path.mkdir(parents=True, exist_ok=True)
    work_database = WorkDatabase(tmp_path / "work.db")
    work_database.initialize()
    selected: list[tuple[int, dict[str, str]]] = []
    texts: dict[int, str] = {}
    for scene_index, scene in enumerate(SCENES):
        for item_index in range(per_scene):
            marker = alphabetic_marker(scene_index * per_scene + item_index)
            text = (
                "Careful learners review practical vocabulary about "
                f"{scene.key} {marker} today."
            )
            item_id = work_database.upsert_raw(
                source_name="Open Example",
                source_item_id=f"{scene.key}-{item_index}",
                source_url=f"https://example.test/{scene.key}/{item_index}",
                source_author=f"author-{scene_index}",
                license_name="CC BY 4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
                text=text,
            )
            work_database.mark_stage(item_id, "clean", payload={"clean_text": text})
            work_database.mark_stage(item_id, "dedupe", payload={"simhash64": "0"})
            work_database.mark_stage(
                item_id,
                "classify",
                payload={"top_scene": scene.top_key, "sub_scene": scene.key},
            )
            selected.append(
                (item_id, {"top_scene": scene.top_key, "sub_scene": scene.key})
            )
            texts[item_id] = text
    work_database.replace_stage("select", selected)
    claimed = work_database.claim_translation_batch(len(selected))
    assert claimed is not None
    work_database.checkpoint_translation_batch(
        [(item.id, f"译文 {item.id}", ()) for item in claimed.items],
        model_version="fixture-translator",
        selection_generation=claimed.selection_generation,
    )
    for item_id, text in texts.items():
        work_database.mark_stage(item_id, "variants", payload=_variant_payload(text))

    return build_database(
        work_database,
        tmp_path / "content-v2.candidate.db",
        tmp_path / "quality-report.json",
        tmp_path / "sources.json",
        preserve_ids_from=preserve_ids_from,
    )


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


def test_builder_writes_scene_metadata_stable_ids_and_query_indexes(tmp_path: Path) -> None:
    result = build_fixture_database(tmp_path, per_scene=3)

    assert result.sentence_count == 96
    assert result.variant_count == 288
    with sqlite3.connect(result.database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM top_scenes").fetchone()[0] == 8
        assert connection.execute("SELECT COUNT(*) FROM sub_scenes").fetchone()[0] == 32
        assert connection.execute("SELECT COUNT(*) FROM sentences").fetchone()[0] == 96
        sentence_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(sentences)")
        }
        variant_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(question_variants)")
        }
        assert "idx_sentences_scene_random" in sentence_indexes
        assert "idx_variants_sentence_difficulty" in variant_indexes
        sentence = connection.execute(
            "SELECT id, normalized_hash, random_key, source_item_id FROM sentences ORDER BY id"
        ).fetchone()
    assert sentence is not None
    assert sentence[0] == f"s_{sentence[1][:16]}"
    assert sentence[2] == int.from_bytes(bytes.fromhex(sentence[1])[:8], "big") & ((1 << 63) - 1)
    assert sentence[3]


def test_stable_sentence_id_uses_normalized_sha256_not_process_hash() -> None:
    text = "  DON'T   stop learning today! "
    digest = hashlib.sha256(b"don't stop learning today!").hexdigest()

    assert builder.stable_sentence_id(text) == f"s_{digest[:16]}"


def test_builder_preserves_legacy_sentence_question_ids_and_alias_union(tmp_path: Path) -> None:
    fixture_root = tmp_path / "source"
    first = build_fixture_database(fixture_root)
    with sqlite3.connect(first.database) as connection:
        row = connection.execute(
            """
            SELECT s.text, s.normalized_hash, q.difficulty, q.canonical_answer
            FROM sentences AS s
            JOIN question_variants AS q ON q.sentence_id = s.id
            WHERE q.difficulty = 'easy'
            ORDER BY s.id
            LIMIT 1
            """
        ).fetchone()
    assert row is not None
    text, digest, difficulty, answer = row
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as connection:
        connection.executescript(
            """
            CREATE TABLE sentences(id TEXT PRIMARY KEY, normalized_hash TEXT NOT NULL UNIQUE);
            CREATE TABLE question_variants(
                id TEXT PRIMARY KEY,
                sentence_id TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                canonical_answer TEXT NOT NULL
            );
            CREATE TABLE aliases(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_variant_id TEXT NOT NULL,
                alias TEXT NOT NULL
            );
            """
        )
        connection.execute("INSERT INTO sentences VALUES ('s0042', ?)", (digest,))
        connection.execute(
            "INSERT INTO question_variants VALUES ('legacy-easy-id', 's0042', ?, ?)",
            (difficulty, answer),
        )
        connection.execute(
            "INSERT INTO aliases(question_variant_id, alias) VALUES ('legacy-easy-id', 'old alias')"
        )

    rebuilt = build_fixture_database(tmp_path / "rebuilt", preserve_ids_from=legacy)
    with sqlite3.connect(rebuilt.database) as connection:
        sentence_row = connection.execute(
            "SELECT id FROM sentences WHERE normalized_hash = ?", (digest,)
        ).fetchone()
        variant_row = connection.execute(
            "SELECT id FROM question_variants WHERE sentence_id = ? AND difficulty = ?",
            ("s0042", difficulty),
        ).fetchone()
        aliases = {
            alias
            for (alias,) in connection.execute(
                "SELECT alias FROM aliases WHERE question_variant_id = 'legacy-easy-id'"
            )
        }
    assert sentence_row == ("s0042",)
    assert variant_row == ("legacy-easy-id",)
    assert "old alias" in aliases


def test_builder_extends_stable_id_prefix_on_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = builder.normalized_hash

    def colliding_digest(text: str) -> str:
        digest = original(text)
        if "daily_home" in text:
            suffix = "1" * 48
            if "lexemeaa" not in text:
                suffix = "2" * 48
            return "0123456789abcdef" + suffix
        return digest

    monkeypatch.setattr(builder, "normalized_hash", colliding_digest)

    result = build_fixture_database(tmp_path, per_scene=2)
    with sqlite3.connect(result.database) as connection:
        ids = [
            row[0]
            for row in connection.execute(
                "SELECT id FROM sentences WHERE sub_scene_key = 'daily_home' ORDER BY id"
            )
        ]
    assert ids == ["s_0123456789abcdef", "s_0123456789abcdef22222222"]


def test_builder_rejects_missing_or_invalid_variant_payload_without_replacing_candidate(
    tmp_path: Path,
) -> None:
    work_database = WorkDatabase(tmp_path / "work.db")
    work_database.initialize()
    candidate = tmp_path / "candidate.db"
    candidate.write_bytes(b"existing candidate")

    with pytest.raises(BuildError, match="variants"):
        build_database(
            work_database,
            candidate,
            tmp_path / "report.json",
            tmp_path / "sources.json",
        )

    assert candidate.read_bytes() == b"existing candidate"


@pytest.mark.parametrize("invalid_case", ["count", "difficulty", "span", "word_count"])
def test_builder_rejects_malformed_variant_payload(
    tmp_path: Path, invalid_case: str
) -> None:
    fixture_root = tmp_path / "fixture"
    first = build_fixture_database(fixture_root)
    work_database = WorkDatabase(fixture_root / "work.db")
    with work_database.connect() as connection:
        item_id, raw_payload = connection.execute(
            """
            SELECT item_id, payload_json
            FROM stage_results
            WHERE stage = 'variants'
            ORDER BY item_id
            LIMIT 1
            """
        ).fetchone()
        payload = json.loads(raw_payload)
        if invalid_case == "count":
            payload["variants"].pop()
        elif invalid_case == "difficulty":
            payload["variants"][1]["difficulty"] = "easy"
        elif invalid_case == "span":
            payload["variants"][0]["answer_end"] += 1
        else:
            payload["variants"][0]["answer_word_count"] += 1
        connection.execute(
            "UPDATE stage_results SET payload_json = ? WHERE item_id = ? AND stage = 'variants'",
            (json.dumps(payload), item_id),
        )

    before = first.database.read_bytes()
    with pytest.raises(BuildError, match="variants|difficulty|区间|word_count"):
        build_database(
            work_database,
            first.database,
            first.report,
            first.sources,
        )
    assert first.database.read_bytes() == before


@pytest.mark.parametrize("invalid_word_count", [0, -1, 5])
def test_builder_rejects_answer_word_count_outside_one_to_four(
    tmp_path: Path, invalid_word_count: int
) -> None:
    fixture_root = tmp_path / "fixture"
    first = build_fixture_database(fixture_root)
    work_database = WorkDatabase(fixture_root / "work.db")
    with work_database.connect() as connection:
        item_id, text, raw_payload = connection.execute(
            """
            SELECT variants.item_id, raw.text, variants.payload_json
            FROM stage_results AS variants
            JOIN raw_items AS raw ON raw.id = variants.item_id
            WHERE variants.stage = 'variants'
            ORDER BY variants.item_id
            LIMIT 1
            """
        ).fetchone()
        payload = json.loads(raw_payload)
        variant = payload["variants"][0]
        if invalid_word_count == 5:
            answer = " ".join(text.split()[:5])
            variant["answer_start"] = 0
            variant["answer_end"] = len(answer)
            variant["canonical_answer"] = answer
        variant["answer_word_count"] = invalid_word_count
        connection.execute(
            "UPDATE stage_results SET payload_json = ? WHERE item_id = ? AND stage = 'variants'",
            (json.dumps(payload), item_id),
        )

    old_bytes = {
        path: path.read_bytes() for path in (first.database, first.report, first.sources)
    }
    with pytest.raises(BuildError, match="answer_word_count"):
        build_database(
            work_database,
            first.database,
            first.report,
            first.sources,
        )
    assert {
        path: path.read_bytes() for path in (first.database, first.report, first.sources)
    } == old_bytes


@pytest.mark.parametrize(
    ("failure_target", "targets_exist"),
    [("report", True), ("sources", True), ("sources", False)],
)
def test_builder_rolls_back_all_outputs_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_target: str,
    targets_exist: bool,
) -> None:
    fixture_root = tmp_path / "fixture"
    build_fixture_database(fixture_root)
    work_database = WorkDatabase(fixture_root / "work.db")
    output_root = tmp_path / "atomic"
    database = output_root / "candidate.db"
    report = output_root / "quality-report.json"
    sources = output_root / "sources.json"
    targets = {"database": database, "report": report, "sources": sources}
    output_root.mkdir()
    before: dict[Path, bytes | None] = {}
    for name, path in targets.items():
        payload = f"old-{name}".encode()
        if targets_exist:
            path.write_bytes(payload)
            before[path] = payload
        else:
            before[path] = None

    original_replace = Path.replace
    failing_temporary = targets[failure_target].with_suffix(
        targets[failure_target].suffix + ".tmp"
    )
    injected = False

    def replace_with_failure(path: Path, target: Path) -> Path:
        nonlocal injected
        if path == failing_temporary and not injected:
            injected = True
            raise OSError(f"simulated {failure_target} replace failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace_with_failure)

    with pytest.raises(OSError, match=failure_target):
        build_database(work_database, database, report, sources)

    assert injected is True
    for path, old_payload in before.items():
        if old_payload is None:
            assert not path.exists()
        else:
            assert path.read_bytes() == old_payload


def test_builder_rolls_back_all_outputs_when_backup_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_root = tmp_path / "fixture"
    build_fixture_database(fixture_root)
    work_database = WorkDatabase(fixture_root / "work.db")
    output_root = tmp_path / "atomic"
    output_root.mkdir()
    targets = (
        output_root / "candidate.db",
        output_root / "quality-report.json",
        output_root / "sources.json",
    )
    before = {}
    for index, path in enumerate(targets):
        payload = f"old-{index}".encode()
        path.write_bytes(payload)
        before[path] = payload

    original_unlink = Path.unlink
    injected = False

    def unlink_with_failure(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal injected
        if path.suffix == ".bak" and not injected:
            injected = True
            raise OSError("simulated backup cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink_with_failure)

    with pytest.raises(BuildError, match="清理备份"):
        build_database(work_database, *targets)

    assert injected is True
    assert {path: path.read_bytes() for path in targets} == before
