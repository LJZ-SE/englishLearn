from datetime import date

import pytest

from listening_cloze.application.learning_contracts import (
    DailyGoalSummary,
    HistoryFilter,
    LearningCenterDataSource,
    TrendRange,
    VocabularyItem,
    VocabularyReason,
    normalize_term,
)


def test_daily_goal_accepts_only_supported_targets() -> None:
    summary = DailyGoalSummary.build(target=30, completed=18)

    assert summary.remaining == 12
    assert summary.percent == 0.6
    assert summary.completed_state is False
    with pytest.raises(ValueError, match="每日目标"):
        DailyGoalSummary.build(target=25, completed=0)


def test_daily_goal_caps_progress_after_target_is_completed() -> None:
    summary = DailyGoalSummary.build(target=10, completed=14)

    assert summary.remaining == 0
    assert summary.percent == 1.0
    assert summary.completed_state is True


def test_vocabulary_contract_keeps_a_multiword_phrase_as_one_term() -> None:
    item = VocabularyItem(
        entry_id="v1",
        term="take part in",
        sentence="We take part in it.",
        translation="我们参与其中。",
        source_question_id="q1",
        reason=VocabularyReason.WRONG,
        encounter_count=2,
        created_at="2026-07-24T10:00:00+00:00",
        updated_at="2026-07-24T11:00:00+00:00",
    )

    assert item.term == "take part in"
    assert normalize_term("  Take   Part In ") == "take part in"


def test_learning_data_source_protocol_declares_all_page_queries() -> None:
    expected = {
        "scene_filters",
        "dashboard",
        "session_history",
        "wrong_questions",
        "vocabulary",
        "statistics",
    }

    assert expected <= set(LearningCenterDataSource.__dict__)
    assert HistoryFilter.ALL.value == "all"
    assert TrendRange.DAYS_7.value == "7d"
    assert date(2026, 7, 24).isoformat() == "2026-07-24"
