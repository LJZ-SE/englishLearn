from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

DAILY_GOALS = frozenset({10, 20, 30, 50})


class PageKey(StrEnum):
    HOME = "home"
    PRACTICE_CONFIG = "practice-config"
    HISTORY = "history"
    WRONG_BOOK = "wrong-book"
    VOCABULARY = "vocabulary"
    STATISTICS = "statistics"
    SETTINGS = "settings"


class PracticeType(StrEnum):
    QUANTITATIVE = "quantitative"
    ENDLESS = "endless"
    WRONG_REVIEW = "wrong_review"
    VOCABULARY_REVIEW = "vocabulary_review"


class HistoryFilter(StrEnum):
    ALL = "all"
    QUANTITATIVE = "quantitative"
    ENDLESS = "endless"
    WRONG_REVIEW = "wrong_review"
    VOCABULARY_REVIEW = "vocabulary_review"


class TrendRange(StrEnum):
    DAYS_7 = "7d"
    DAYS_30 = "30d"


class VocabularyReason(StrEnum):
    WRONG = "wrong"
    REVEALED = "revealed"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class ResumeSummary:
    available: bool
    session_id: str
    title: str
    subtitle: str
    completed: int
    target: int
    progress: float
    mode: PracticeType


@dataclass(frozen=True, slots=True)
class DailyGoalSummary:
    target: int
    completed: int
    remaining: int
    percent: float
    completed_state: bool

    @classmethod
    def build(cls, *, target: int, completed: int) -> DailyGoalSummary:
        if target not in DAILY_GOALS:
            raise ValueError("每日目标只支持 10、20、30 或 50 题")
        if isinstance(completed, bool) or completed < 0:
            raise ValueError("今日完成题数必须是非负整数")
        return cls(
            target=target,
            completed=completed,
            remaining=max(0, target - completed),
            percent=min(1.0, completed / target),
            completed_state=completed >= target,
        )


@dataclass(frozen=True, slots=True)
class PendingSummary:
    total: int
    vocabulary_count: int
    phrase_count: int
    confusing_count: int

    def __post_init__(self) -> None:
        if self.total != (
            self.vocabulary_count + self.phrase_count + self.confusing_count
        ):
            raise ValueError("待掌握分组数量之和必须等于总数")


@dataclass(frozen=True, slots=True)
class SessionSummary:
    session_id: str
    practice_type: PracticeType
    mode_label: str
    scene_label: str
    difficulty_label: str
    completed: int
    target: int
    accuracy: float
    duration_seconds: int
    completed_state: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class WrongQuestionItem:
    question_id: str
    sentence: str
    translation: str
    answer: str
    scene_label: str
    review_correct_streak: int
    required_review_streak: int
    first_wrong_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class VocabularyItem:
    entry_id: str
    term: str
    sentence: str
    translation: str
    source_question_id: str
    reason: VocabularyReason
    encounter_count: int
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not normalize_term(self.term):
            raise ValueError("词汇或短语不能为空")
        if self.encounter_count < 1:
            raise ValueError("词汇遇到次数必须至少为 1")


@dataclass(frozen=True, slots=True)
class TrendPoint:
    activity_date: date
    label: str
    completed: int


@dataclass(frozen=True, slots=True)
class LearningSummary:
    total_completed: int
    unique_practiced: int
    accuracy: float
    current_streak_days: int
    longest_streak_days: int
    total_duration_seconds: int
    pending: int


@dataclass(frozen=True, slots=True)
class DistributionItem:
    key: str
    label: str
    count: int
    percent: float


@dataclass(frozen=True, slots=True)
class SceneFilterItem:
    key: str
    label: str


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    resume: ResumeSummary
    daily_goal: DailyGoalSummary
    pending: PendingSummary
    recent_sessions: tuple[SessionSummary, ...]
    trend_7_days: tuple[TrendPoint, ...]
    summary: LearningSummary


@dataclass(frozen=True, slots=True)
class StatisticsSnapshot:
    daily_goal: DailyGoalSummary
    range_key: TrendRange
    trend: tuple[TrendPoint, ...]
    summary: LearningSummary
    scene_distribution: tuple[DistributionItem, ...]
    difficulty_distribution: tuple[DistributionItem, ...]


@dataclass(frozen=True, slots=True)
class PageResult[ItemT]:
    items: tuple[ItemT, ...]
    has_more: bool


class LearningCenterDataSource(Protocol):
    def scene_filters(self) -> tuple[SceneFilterItem, ...]: ...

    def dashboard(self, *, local_date: date) -> DashboardSnapshot: ...

    def session_history(
        self,
        *,
        filter_key: HistoryFilter,
        offset: int,
        limit: int,
    ) -> PageResult[SessionSummary]: ...

    def wrong_questions(
        self,
        *,
        scene_key: str | None,
        search_text: str,
    ) -> tuple[WrongQuestionItem, ...]: ...

    def vocabulary(self, *, search_text: str) -> tuple[VocabularyItem, ...]: ...

    def statistics(
        self,
        *,
        range_key: TrendRange,
        local_date: date,
    ) -> StatisticsSnapshot: ...


def normalize_term(term: str) -> str:
    return " ".join(term.casefold().split())
