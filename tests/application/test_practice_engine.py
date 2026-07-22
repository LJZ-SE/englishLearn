import random
from pathlib import Path

import pytest

import listening_cloze.application.practice_engine as practice_engine_module
from listening_cloze.application.practice_engine import PracticeEngine, PracticeMode
from listening_cloze.domain.models import Category, Difficulty, Question
from listening_cloze.domain.session import EndlessDifficultyState
from listening_cloze.infrastructure.database import ContentQuestion, UserRepository


class FakeContentRepository:
    def __init__(self, questions: list[ContentQuestion]) -> None:
        self.questions = questions
        self.sample_calls: list[dict[str, object]] = []
        self.get_by_ids_calls: list[list[str]] = []
        self.list_all_calls = 0

    def list_questions(
        self,
        *,
        category: str | None = None,
        difficulty: str | None = None,
    ) -> list[ContentQuestion]:
        self.list_all_calls += 1
        return [
            question
            for question in self.questions
            if (category in (None, "all") or question.category == category)
            and (difficulty in (None, "all") or question.difficulty == difficulty)
        ]

    def sample_questions(
        self,
        *,
        top_scene: str | None,
        sub_scene: str | None,
        difficulty: str,
        limit: int,
        exclude_ids: frozenset[str],
        seed: int,
    ) -> list[ContentQuestion]:
        self.sample_calls.append(
            {
                "top_scene": top_scene,
                "sub_scene": sub_scene,
                "difficulty": difficulty,
                "limit": limit,
                "exclude_ids": exclude_ids,
                "seed": seed,
            }
        )
        candidates = [
            question
            for question in self.questions
            if (top_scene is None or question.top_scene == top_scene)
            and (sub_scene is None or question.sub_scene == sub_scene)
            and question.difficulty == difficulty
            and question.id not in exclude_ids
        ]
        random.Random(seed).shuffle(candidates)
        return candidates[:limit]

    def get_questions_by_ids(self, ids: list[str] | tuple[str, ...]) -> list[ContentQuestion]:
        requested = list(ids)
        self.get_by_ids_calls.append(requested)
        by_id = {question.id: question for question in self.questions}
        return [by_id[question_id] for question_id in requested if question_id in by_id]


def test_scene_selection_rejects_a_sub_scene_from_another_top_scene() -> None:
    with pytest.raises(ValueError, match="子场景"):
        practice_engine_module.SceneSelection("travel", "daily_home")


def test_question_stores_scene_strings_and_accepts_legacy_category_keyword() -> None:
    hierarchical = Question(
        id="hierarchical",
        source_sentence_id="sentence-hierarchical",
        sentence="We checked into the hotel.",
        top_scene="travel",
        sub_scene="travel_hotel",
        difficulty=Difficulty.EASY,
        canonical_answer="hotel",
    )
    legacy = Question(
        id="legacy",
        source_sentence_id="sentence-legacy",
        sentence="We cooked dinner at home.",
        category=Category.DAILY,
        difficulty=Difficulty.EASY,
        canonical_answer="dinner",
    )

    assert (hierarchical.top_scene, hierarchical.sub_scene) == (
        "travel",
        "travel_hotel",
    )
    assert (legacy.top_scene, legacy.sub_scene) == ("daily", None)
    assert legacy.category is Category.DAILY


def test_quantitative_mode_requests_only_required_candidate_window(tmp_path: Path) -> None:
    content = FakeContentRepository(
        [
            _question(
                f"q-{index}",
                "easy",
                "word",
                top_scene="travel",
                sub_scene="travel_hotel",
            )
            for index in range(40)
        ]
    )
    engine = PracticeEngine(
        content,
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(41),
    )

    engine.start_quantitative(
        scene=practice_engine_module.SceneSelection("travel", "travel_hotel"),
        difficulty=Difficulty.EASY,
        count=10,
    )

    assert content.sample_calls[0]["limit"] == 30
    assert content.sample_calls[0]["top_scene"] == "travel"
    assert content.sample_calls[0]["sub_scene"] == "travel_hotel"
    assert content.list_all_calls == 0


def test_quantitative_sampling_seed_is_reproducible(tmp_path: Path) -> None:
    questions = [_question(f"q-{index}", "easy", "word") for index in range(40)]
    first_content = FakeContentRepository(questions)
    second_content = FakeContentRepository(questions)

    PracticeEngine(
        first_content,
        UserRepository(tmp_path / "first.db"),
        rng=random.Random(42),
    ).start_quantitative(category="daily", difficulty=Difficulty.EASY, count=10)
    PracticeEngine(
        second_content,
        UserRepository(tmp_path / "second.db"),
        rng=random.Random(42),
    ).start_quantitative(category="daily", difficulty=Difficulty.EASY, count=10)

    assert first_content.sample_calls[0]["seed"] == second_content.sample_calls[0]["seed"]


def test_quantitative_mode_reports_candidate_shortage_without_full_scan(
    tmp_path: Path,
) -> None:
    content = FakeContentRepository([_question(f"q-{index}", "easy", "word") for index in range(4)])
    engine = PracticeEngine(
        content,
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(43),
    )

    with pytest.raises(ValueError, match="题库只有 4 道"):
        engine.start_quantitative(category="daily", difficulty=Difficulty.EASY, count=5)

    assert content.list_all_calls == 0


def test_endless_mode_keeps_only_current_and_next_two_questions(tmp_path: Path) -> None:
    content = FakeContentRepository(
        [_question(f"easy-{index}", "easy", "word") for index in range(12)]
        + [_question(f"medium-{index}", "medium", "word") for index in range(12)]
    )
    engine = PracticeEngine(
        content,
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(44),
    )
    engine.start_endless(category="daily")

    for _index in range(7):
        assert len(engine.items) == 3
        assert engine.position == 0
        assert len(engine.prefetch_window) == 3
        engine.submit(["word"])
        engine.next_question()

    assert content.list_all_calls == 0
    assert all(len(call["exclude_ids"]) <= 2 for call in content.sample_calls)


def test_resume_loads_only_saved_question_ids_and_maps_legacy_category(tmp_path: Path) -> None:
    questions = [
        _question(
            f"q-{index}",
            "easy",
            "word",
            top_scene="culture",
            sub_scene="culture_movies",
        )
        for index in range(3)
    ]
    users = UserRepository(tmp_path / "user.db")
    question_ids = [question.id for question in questions]
    users.save_session(
        "legacy-session",
        mode="endless",
        state={
            "question_ids": question_ids,
            "position": 1,
            "category": "movies",
            "difficulty": "easy",
            "attempt": {
                "first_result": False,
                "submission_count": 1,
                "answer_revealed": False,
                "can_advance": False,
            },
        },
    )
    content = FakeContentRepository(questions)
    engine = PracticeEngine(content, users, rng=random.Random(45))

    assert engine.resume_latest() is True

    assert content.get_by_ids_calls == [question_ids]
    assert content.list_all_calls == 0
    assert engine.current.question.id == "q-1"
    assert engine.scene == practice_engine_module.SceneSelection("culture", None)
    corrected = engine.submit(["word"])
    assert corrected.is_correct
    assert corrected.counted_correct is False


def test_new_session_state_persists_hierarchical_scene_without_category(tmp_path: Path) -> None:
    users = UserRepository(tmp_path / "user.db")
    engine = PracticeEngine(
        FakeContentRepository(
            [
                _question(
                    "q-1",
                    "easy",
                    "word",
                    top_scene="travel",
                    sub_scene="travel_hotel",
                )
            ]
        ),
        users,
        rng=random.Random(46),
    )

    engine.start_quantitative(
        scene=practice_engine_module.SceneSelection("travel", "travel_hotel"),
        difficulty=Difficulty.EASY,
        count=1,
    )

    record = users.load_unfinished_session()
    assert record is not None
    assert record.state["top_scene"] == "travel"
    assert record.state["sub_scene"] == "travel_hotel"
    assert "category" not in record.state


def test_quantitative_first_wrong_then_correct_keeps_wrong_statistic(tmp_path: Path) -> None:
    content = FakeContentRepository([_question("q1", "easy", "take part in")])
    users = UserRepository(tmp_path / "user.db")
    engine = PracticeEngine(content, users, rng=random.Random(7))
    engine.start_quantitative(category="daily", difficulty=Difficulty.EASY, count=1)

    first = engine.submit(["take", "part", "on"])
    second = engine.submit(["take", "part", "in"])

    assert not first.is_correct
    assert first.mascot_kind == "incorrect"
    assert second.is_correct
    assert second.mascot_kind == "correct"
    assert second.counted_correct is False
    assert engine.stats.correct == 0
    assert engine.stats.wrong == 1
    assert engine.can_advance
    progress = users.get_question_progress("q1")
    assert progress is not None
    assert progress.first_correct is False
    assert progress.attempt_count == 2


def test_reveal_answer_counts_as_wrong_and_allows_next_question(tmp_path: Path) -> None:
    content = FakeContentRepository([_question("q1", "medium", "do not", ("don't",))])
    users = UserRepository(tmp_path / "user.db")
    engine = PracticeEngine(content, users, rng=random.Random(8))
    engine.start_quantitative(category="daily", difficulty=Difficulty.MEDIUM, count=1)

    answer = engine.reveal_answer()

    assert answer == "do not"
    assert engine.stats.wrong == 1
    assert engine.stats.viewed_answers == 1
    assert engine.can_advance
    assert users.get_question_progress("q1").first_correct is False


def test_endless_five_first_try_correct_answers_upgrade_next_queue_to_medium(
    tmp_path: Path,
) -> None:
    questions = [
        _question(f"easy-{index}", "easy", "word", sentence_id=f"easy-s-{index}")
        for index in range(8)
    ] + [
        _question(f"medium-{index}", "medium", "phrase here", sentence_id=f"medium-s-{index}")
        for index in range(5)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(3),
    )
    engine.start_endless(category="daily")

    for index in range(5):
        result = engine.submit(["word"])
        assert result.is_correct
        if index < 4:
            engine.next_question()

    assert result.difficulty_changed
    assert result.mascot_kind == "level_up"
    assert result.feedback_animation.startswith("level_up_")
    assert engine.endless_state.difficulty is Difficulty.MEDIUM
    engine.next_question()
    assert engine.current.question.difficulty is Difficulty.MEDIUM
    assert all(item.question.difficulty is Difficulty.MEDIUM for item in engine.prefetch_window)


def test_endless_five_first_try_errors_use_level_down_feedback(tmp_path: Path) -> None:
    questions = [
        _question(f"medium-{index}", "medium", "word", sentence_id=f"m-{index}")
        for index in range(8)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(17),
    )
    engine._reset(PracticeMode.ENDLESS, "daily")
    engine.endless_state = EndlessDifficultyState(Difficulty.MEDIUM)
    engine._fill_endless_queue()
    engine._begin_current()

    for index in range(5):
        result = engine.submit(["wrong"])
        engine.reveal_answer()
        if index < 4:
            engine.next_question()

    assert result.difficulty_changed
    assert result.mascot_kind == "level_down"
    assert result.feedback_animation.startswith("level_down_")


def test_quantitative_session_has_fixed_order_and_three_item_prefetch_window(
    tmp_path: Path,
) -> None:
    questions = [
        _question(f"q-{index}", "hard", "answer", sentence_id=f"s-{index}") for index in range(5)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(11),
    )

    engine.start_quantitative(category="daily", difficulty=Difficulty.HARD, count=5)

    assert engine.mode is PracticeMode.QUANTITATIVE
    assert len(engine.prefetch_window) == 3
    assert engine.prefetch_window[0] == engine.current
    assert len({item.question.id for item in engine.items}) == 5


def test_session_resume_restores_order_stats_attempt_and_endless_streak(tmp_path: Path) -> None:
    questions = [
        _question(f"q-{index}", "easy", "word", sentence_id=f"s-{index}") for index in range(8)
    ]
    database = tmp_path / "user.db"
    users = UserRepository(database)
    first = PracticeEngine(FakeContentRepository(questions), users, rng=random.Random(12))
    first.start_endless(category="daily")
    original_order = [item.question.id for item in first.items]
    first.submit(["wrong"])

    resumed = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(database),
        rng=random.Random(99),
    )

    assert resumed.has_unfinished_session
    assert resumed.resume_latest()
    assert [item.question.id for item in resumed.items] == original_order
    assert resumed.stats.wrong == 1
    assert resumed.endless_state is not None
    assert resumed.endless_state.incorrect_streak == 1
    assert resumed.progress_states == ["wrong"]

    corrected = resumed.submit(["word"])
    assert corrected.is_correct
    assert not corrected.counted_correct
    assert resumed.stats.wrong == 1


def test_quantitative_progress_states_and_audio_skip_replacement_do_not_change_stats(
    tmp_path: Path,
) -> None:
    questions = [
        _question(f"q-{index}", "easy", "word", sentence_id=f"s-{index}") for index in range(8)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(13),
    )
    engine.start_quantitative(category="daily", difficulty=Difficulty.EASY, count=5)
    failed_id = engine.current.question.id

    engine.skip_current_for_audio_error()

    assert engine.current.question.id != failed_id
    assert len(engine.items) == 5
    assert engine.stats.completed == 0
    assert engine.progress_states == ["current", "pending", "pending", "pending", "pending"]

    engine.submit(["wrong"])
    assert engine.progress_states == ["wrong", "pending", "pending", "pending", "pending"]


def test_persisted_question_history_is_used_by_selector(tmp_path: Path) -> None:
    questions = [
        _question("mastered", "easy", "word", sentence_id="mastered-s"),
        _question("unseen", "easy", "word", sentence_id="unseen-s"),
    ]
    users = UserRepository(tmp_path / "user.db")
    users.record_attempt("mastered", is_correct=True)
    engine = PracticeEngine(
        FakeContentRepository(questions),
        users,
        rng=random.Random(1),
    )

    engine.start_quantitative(category="daily", difficulty=Difficulty.EASY, count=1)

    assert engine.current.question.id == "unseen"


def test_quantitative_wrong_questions_can_start_immediate_review(tmp_path: Path) -> None:
    questions = [
        _question(f"q-{index}", "easy", "word", sentence_id=f"s-{index}") for index in range(5)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(18),
    )
    engine.start_quantitative(category="daily", difficulty=Difficulty.EASY, count=5)
    wrong_id = engine.current.question.id
    engine.submit(["wrong"])
    engine.reveal_answer()
    for _index in range(4):
        assert engine.next_question()
        engine.submit(["word"])

    assert engine.has_review_items
    engine.start_review()

    assert engine.mode is PracticeMode.QUANTITATIVE
    assert len(engine.items) == 1
    assert engine.current.question.id == wrong_id
    assert engine.stats.completed == 0


def _question(
    question_id: str,
    difficulty: str,
    answer: str,
    aliases: tuple[str, ...] = (),
    *,
    sentence_id: str | None = None,
    top_scene: str = "daily",
    sub_scene: str = "daily_home",
) -> ContentQuestion:
    sentence = f"You should {answer} today."
    start = sentence.index(answer)
    return ContentQuestion(
        id=question_id,
        sentence_id=sentence_id or f"sentence-{question_id}",
        sentence_text=sentence,
        category=top_scene,
        top_scene=top_scene,
        sub_scene=sub_scene,
        source_url=f"https://example.test/{question_id}",
        normalized_hash=f"hash-{question_id}",
        difficulty=difficulty,
        answer_start=start,
        answer_end=start + len(answer),
        canonical_answer=answer,
        answer_word_count=len(answer.split()),
        difficulty_score=1.0,
        rationale="测试数据",
        aliases=aliases,
    )
