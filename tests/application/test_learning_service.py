from datetime import date
from pathlib import Path

from listening_cloze.application.learning_contracts import HistoryFilter, TrendRange
from listening_cloze.application.learning_models import LearningCenterViewModel
from listening_cloze.application.learning_service import LearningCenterService
from listening_cloze.infrastructure.database import (
    ContentQuestion,
    SceneMetadata,
    UserRepository,
)


class FakeLearningContent:
    def __init__(self, questions: list[ContentQuestion]) -> None:
        self.questions = questions

    def list_scenes(self) -> list[SceneMetadata]:
        return [
            SceneMetadata(
                key="daily",
                label="日常生活",
                children=(SceneMetadata(key="daily_home", label="家庭家务"),),
            ),
            SceneMetadata(
                key="cet",
                label="四六级考试",
                children=(SceneMetadata(key="cet_4", label="四级真题"),),
            ),
        ]

    def get_questions_by_ids(self, ids: list[str]) -> list[ContentQuestion]:
        by_id = {question.id: question for question in self.questions}
        return [by_id[question_id] for question_id in ids if question_id in by_id]


def _question(
    question_id: str,
    answer: str,
    *,
    top_scene: str = "daily",
    sub_scene: str = "daily_home",
) -> ContentQuestion:
    sentence = f"We should {answer} today."
    start = sentence.index(answer)
    return ContentQuestion(
        id=question_id,
        sentence_id=f"s-{question_id}",
        sentence_text=sentence,
        translation_zh="我们今天应该这样做。",
        category=top_scene,
        top_scene=top_scene,
        sub_scene=sub_scene,
        source_url="https://example.test",
        normalized_hash=f"hash-{question_id}",
        difficulty="easy",
        answer_start=start,
        answer_end=start + len(answer),
        canonical_answer=answer,
        answer_word_count=len(answer.split()),
        difficulty_score=1.0,
        rationale="测试题",
        aliases=(),
    )


def _service(
    tmp_path: Path,
    questions: list[ContentQuestion],
) -> tuple[LearningCenterService, UserRepository]:
    users = UserRepository(tmp_path / "user.db")
    return LearningCenterService(FakeLearningContent(questions), users), users


def test_dashboard_uses_persisted_session_activity_and_pending_groups(
    tmp_path: Path,
) -> None:
    service, users = _service(
        tmp_path,
        [_question("word", "listen"), _question("phrase", "take part in")],
    )
    users.set_setting("daily_goal", 10)
    users.record_attempt("word", is_correct=False)
    users.record_view_answer("phrase")
    users.record_daily_activity(
        "2026-07-24",
        completed_delta=2,
        correct_delta=1,
        duration_delta=90,
    )
    users.save_session(
        "resume",
        mode="quantitative",
        state={
            "practice_type": "quantitative",
            "top_scene": "cet",
            "sub_scene": "cet_4",
            "difficulty": "easy",
            "target_count": 10,
            "stats": {"completed": 4, "correct": 3},
            "duration_seconds": 90,
        },
    )

    dashboard = service.dashboard(local_date=date(2026, 7, 24))

    assert dashboard.resume.available
    assert dashboard.resume.subtitle == "CET-4"
    assert dashboard.resume.completed == 4
    assert dashboard.daily_goal.completed == 2
    assert dashboard.pending.total == 2
    assert dashboard.pending.vocabulary_count == 1
    assert dashboard.pending.phrase_count == 1
    assert dashboard.pending.confusing_count == 0
    assert dashboard.summary.total_completed == 2
    assert dashboard.summary.total_duration_seconds == 90


def test_history_wrong_search_vocabulary_and_statistics_are_real_queries(
    tmp_path: Path,
) -> None:
    service, users = _service(tmp_path, [_question("q1", "take part in")])
    users.record_attempt("q1", is_correct=False)
    users.upsert_vocabulary(
        term="take part in",
        source_question_id="q1",
        sentence="We should take part in today.",
        translation="我们今天应该参与。",
        reason="wrong",
    )
    users.record_daily_activity(
        "2026-07-23",
        completed_delta=1,
        correct_delta=0,
        duration_delta=30,
    )
    users.record_daily_activity(
        "2026-07-24",
        completed_delta=1,
        correct_delta=1,
        duration_delta=45,
    )
    users.save_session(
        "review",
        mode="quantitative",
        state={
            "practice_type": "wrong_review",
            "top_scene": "daily",
            "sub_scene": "daily_home",
            "difficulty": "easy",
            "target_count": 1,
            "stats": {"completed": 1, "correct": 1},
        },
    )

    history = service.session_history(
        filter_key=HistoryFilter.WRONG_REVIEW,
        offset=0,
        limit=10,
    )
    wrong = service.wrong_questions(scene_key="daily", search_text="part")
    vocabulary = service.vocabulary(search_text="part")
    statistics = service.statistics(
        range_key=TrendRange.DAYS_7,
        local_date=date(2026, 7, 24),
    )

    assert [item.session_id for item in history.items] == ["review"]
    assert wrong[0].answer == "take part in"
    assert vocabulary[0].term == "take part in"
    assert statistics.summary.current_streak_days == 2
    assert statistics.summary.accuracy == 0.0
    assert statistics.scene_distribution[0].key == "daily"


def test_view_model_maps_real_service_data_and_refreshes_after_removal(
    tmp_path: Path,
) -> None:
    service, users = _service(tmp_path, [_question("q1", "take part in")])
    users.record_attempt("q1", is_correct=False)
    entry = users.upsert_vocabulary(
        term="take part in",
        source_question_id="q1",
        sentence="We should take part in today.",
        translation="我们今天应该参与。",
        reason="wrong",
    )
    users.record_daily_activity(
        "2026-07-24",
        completed_delta=1,
        correct_delta=0,
        duration_delta=60,
    )

    model = LearningCenterViewModel(
        service,
        local_date=lambda: date(2026, 7, 24),
    )

    assert model.dashboard["summary"]["totalCompleted"] == 1
    assert model.dashboard["recentSessions"] == []
    assert model.wrongSceneFilters[0] == {"key": "all", "label": "全部场景"}
    assert model.wrongSceneFilters[1] == {"key": "daily", "label": "日常生活"}
    assert model.wrongItems[0]["answer"] == "take part in"
    assert model.vocabularyItems[0]["isPhrase"] is True
    model.removeVocabulary(entry.entry_id)
    assert model.vocabularyItems == []


def test_dictionary_vocabulary_is_exposed_as_non_reviewable(
    tmp_path: Path,
) -> None:
    service, users = _service(tmp_path, [_question("q1", "listen")])
    users.add_dictionary_vocabulary(term="kind of")

    vocabulary = service.vocabulary(search_text="")
    model = LearningCenterViewModel(
        service,
        local_date=lambda: date(2026, 7, 24),
    )

    assert vocabulary[0].source_kind == "dictionary"
    assert vocabulary[0].source_question_id is None
    assert model.vocabularyItems[0]["sourceKind"] == "dictionary"
    assert model.vocabularyItems[0]["sourceQuestionId"] == ""
    assert model.vocabularyItems[0]["reviewable"] is False
    assert model.vocabularyItems[0]["reason"] == "词典手动添加"


def test_view_model_loads_session_history_in_pages(tmp_path: Path) -> None:
    service, users = _service(tmp_path, [_question("q1", "listen")])
    for index in range(25):
        users.save_session(
            f"session-{index:02d}",
            mode="quantitative",
            state={
                "practice_type": "quantitative",
                "top_scene": "daily",
                "sub_scene": "daily_home",
                "difficulty": "easy",
                "target_count": 10,
                "stats": {"completed": index % 10, "correct": index % 8},
            },
        )

    model = LearningCenterViewModel(
        service,
        local_date=lambda: date(2026, 7, 24),
    )

    assert len(model.historyRecords) == 20
    assert model.historyHasMore
    model.loadMoreHistory()
    assert len(model.historyRecords) == 25
    assert not model.historyHasMore
