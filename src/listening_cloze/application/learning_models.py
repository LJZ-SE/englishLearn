from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from listening_cloze.application.learning_contracts import (
    DashboardSnapshot,
    HistoryFilter,
    LearningCenterDataSource,
    LearningSummary,
    PracticeType,
    SessionSummary,
    StatisticsSnapshot,
    TrendRange,
    VocabularyReason,
)

VOCABULARY_REASON_LABELS = {
    VocabularyReason.WRONG: "答错时自动收录",
    VocabularyReason.REVEALED: "查看答案时自动收录",
    VocabularyReason.MANUAL: "手动收录",
}
SCENE_COLORS = ("#1476F2", "#14B86E", "#9857F5", "#FF7A1A", "#1D9BF0")
DIFFICULTY_COLORS = {
    "easy": "#14B86E",
    "medium": "#FFB020",
    "hard": "#F05252",
    "mixed": "#1476F2",
}
HISTORY_PAGE_SIZE = 20


class MutableLearningCenterDataSource(LearningCenterDataSource, Protocol):
    def remove_vocabulary(self, entry_id: str) -> None: ...

    def mark_mastered(self, question_id: str) -> None: ...

    def set_daily_goal(self, target: int) -> None: ...


class LearningCenterViewModel(QObject):
    dataChanged = Signal()

    def __init__(
        self,
        service: MutableLearningCenterDataSource,
        parent: QObject | None = None,
        *,
        local_date: Callable[[], date] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._local_date = local_date or date.today
        self._history_filter = HistoryFilter.ALL
        self._wrong_scene = ""
        self._wrong_search = ""
        self._vocabulary_search = ""
        self._statistics_range = TrendRange.DAYS_7
        self._dashboard: dict[str, object] = _empty_dashboard()
        self._wrong_scene_filters: list[dict[str, str]] = []
        self._history_records: list[dict[str, object]] = []
        self._history_has_more = False
        self._wrong_items: list[dict[str, object]] = []
        self._vocabulary_items: list[dict[str, object]] = []
        self._statistics: dict[str, object] = _empty_statistics()
        self._error = ""
        self.refresh()

    @Property("QVariantMap", notify=dataChanged)
    def dashboard(self) -> dict[str, object]:
        return dict(self._dashboard)

    @Property("QVariantList", notify=dataChanged)
    def historyRecords(self) -> list[dict[str, object]]:
        return [dict(item) for item in self._history_records]

    @Property(bool, notify=dataChanged)
    def historyHasMore(self) -> bool:
        return self._history_has_more

    @Property(bool, notify=dataChanged)
    def hasMore(self) -> bool:
        return self._history_has_more

    @Property("QVariantList", notify=dataChanged)
    def wrongItems(self) -> list[dict[str, object]]:
        return [dict(item) for item in self._wrong_items]

    @Property("QVariantList", notify=dataChanged)
    def wrongSceneFilters(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._wrong_scene_filters]

    @Property("QVariantList", notify=dataChanged)
    def vocabularyItems(self) -> list[dict[str, object]]:
        return [dict(item) for item in self._vocabulary_items]

    @Property("QVariantMap", notify=dataChanged)
    def statistics(self) -> dict[str, object]:
        return dict(self._statistics)

    @Property(str, notify=dataChanged)
    def historyFilter(self) -> str:
        return self._history_filter.value

    @Property(str, notify=dataChanged)
    def wrongSceneFilter(self) -> str:
        return self._wrong_scene or "all"

    @Property(str, notify=dataChanged)
    def statisticsRange(self) -> str:
        return self._statistics_range.value

    @Property(str, notify=dataChanged)
    def errorText(self) -> str:
        return self._error

    @Slot()
    def refresh(self) -> None:
        try:
            today = self._local_date()
            self._wrong_scene_filters = [
                {"key": item.key, "label": item.label}
                for item in self._service.scene_filters()
            ]
            self._dashboard = _dashboard_to_qml(
                self._service.dashboard(local_date=today),
                local_date=today,
            )
            history_page = self._service.session_history(
                filter_key=self._history_filter,
                offset=0,
                limit=HISTORY_PAGE_SIZE,
            )
            self._history_records = [
                _session_to_qml(item) for item in history_page.items
            ]
            self._history_has_more = history_page.has_more
            self._wrong_items = [
                {
                    "questionId": item.question_id,
                    "sentence": item.sentence,
                    "translation": item.translation,
                    "answer": item.answer,
                    "scene": item.scene_label,
                    "streak": item.review_correct_streak,
                    "requiredStreak": item.required_review_streak,
                    "firstWrongAt": _display_date(item.first_wrong_at),
                    "updatedAt": _display_date(item.updated_at),
                }
                for item in self._service.wrong_questions(
                    scene_key=self._wrong_scene or None,
                    search_text=self._wrong_search,
                )
            ]
            self._vocabulary_items = [
                {
                    "entryId": item.entry_id,
                    "term": item.term,
                    "sentence": item.sentence,
                    "translation": item.translation,
                    "sourceQuestionId": item.source_question_id or "",
                    "sourceKind": item.source_kind,
                    "reviewable": bool(item.source_question_id),
                    "reason": (
                        "词典手动添加"
                        if item.source_kind == "dictionary"
                        else VOCABULARY_REASON_LABELS[item.reason]
                    ),
                    "encounters": item.encounter_count,
                    "createdAt": _display_date(item.created_at),
                    "updatedAt": _display_date(item.updated_at),
                    "isPhrase": len(item.term.split()) > 1,
                    "streak": item.independent_correct_streak,
                    "mastered": item.mastered_at is not None,
                    "masteredAt": _display_date(item.mastered_at or ""),
                    "lastPracticedAt": _display_date(item.last_practiced_at or ""),
                }
                for item in self._service.vocabulary(
                    search_text=self._vocabulary_search
                )
            ]
            self._statistics = _statistics_to_qml(
                self._service.statistics(
                    range_key=self._statistics_range,
                    local_date=today,
                )
            )
            self._error = ""
        except Exception as error:
            self._error = str(error)
        self.dataChanged.emit()

    @Slot(str)
    def setHistoryFilter(self, value: str) -> None:
        self._history_filter = HistoryFilter(value)
        self.refresh()

    @Slot()
    def loadMoreHistory(self) -> None:
        if not self._history_has_more:
            return
        try:
            history_page = self._service.session_history(
                filter_key=self._history_filter,
                offset=len(self._history_records),
                limit=HISTORY_PAGE_SIZE,
            )
            self._history_records.extend(
                _session_to_qml(item) for item in history_page.items
            )
            self._history_has_more = history_page.has_more
            self._error = ""
        except Exception as error:
            self._error = str(error)
        self.dataChanged.emit()

    @Slot()
    def loadMore(self) -> None:
        self.loadMoreHistory()

    @Slot(str)
    def setWrongSceneFilter(self, value: str) -> None:
        self._wrong_scene = "" if value == "all" else value
        self.refresh()

    @Slot(str)
    def setWrongSearch(self, value: str) -> None:
        self._wrong_search = value
        self.refresh()

    @Slot(str)
    def setVocabularySearch(self, value: str) -> None:
        self._vocabulary_search = value
        self.refresh()

    @Slot(str)
    def setStatisticsRange(self, value: str) -> None:
        self._statistics_range = TrendRange(value)
        self.refresh()

    @Slot(str)
    def removeVocabulary(self, entry_id: str) -> None:
        self._service.remove_vocabulary(entry_id)
        self.refresh()

    @Slot(str)
    def markMastered(self, question_id: str) -> None:
        self._service.mark_mastered(question_id)
        self.refresh()

    @Slot(int)
    def setDailyGoal(self, target: int) -> None:
        self._service.set_daily_goal(target)
        self.refresh()


def _dashboard_to_qml(
    snapshot: DashboardSnapshot,
    *,
    local_date: date,
) -> dict[str, object]:
    return {
        "resume": {
            "available": snapshot.resume.available,
            "sessionId": snapshot.resume.session_id,
            "title": snapshot.resume.title,
            "subtitle": snapshot.resume.subtitle,
            "completed": snapshot.resume.completed,
            "target": snapshot.resume.target,
            "progress": snapshot.resume.progress,
            "mode": snapshot.resume.mode.value,
        },
        "dailyGoal": {
            "target": snapshot.daily_goal.target,
            "completed": snapshot.daily_goal.completed,
            "remaining": snapshot.daily_goal.remaining,
            "percent": snapshot.daily_goal.percent,
            "completedState": snapshot.daily_goal.completed_state,
        },
        "pending": {
            "total": snapshot.pending.total,
            "vocabularyCount": snapshot.pending.vocabulary_count,
            "phraseCount": snapshot.pending.phrase_count,
            "confusingCount": snapshot.pending.confusing_count,
        },
        "recentSessions": [
            _session_to_qml(item, relative_to=local_date)
            for item in snapshot.recent_sessions
        ],
        "trend7Days": [
            {"label": item.label, "completed": item.completed}
            for item in snapshot.trend_7_days
        ],
        "summary": _summary_to_qml(snapshot.summary),
    }


def _statistics_to_qml(snapshot: StatisticsSnapshot) -> dict[str, object]:
    return {
        "range": snapshot.range_key.value,
        "trend": [
            {"label": item.label, "completed": item.completed}
            for item in snapshot.trend
        ],
        "summary": _summary_to_qml(snapshot.summary),
        "sceneDistribution": [
            {
                "key": item.key,
                "label": item.label,
                "count": item.count,
                "value": round(item.percent * 100, 1),
                "color": SCENE_COLORS[index % len(SCENE_COLORS)],
            }
            for index, item in enumerate(snapshot.scene_distribution)
        ],
        "difficultyDistribution": [
            {
                "key": item.key,
                "label": item.label,
                "count": item.count,
                "value": round(item.percent * 100, 1),
                "color": DIFFICULTY_COLORS.get(item.key, "#1476F2"),
            }
            for item in snapshot.difficulty_distribution
        ],
    }


def _session_to_qml(
    item: SessionSummary,
    *,
    relative_to: date | None = None,
) -> dict[str, object]:
    return {
        "sessionId": item.session_id,
        "practiceType": item.practice_type.value,
        "modeLabel": item.mode_label,
        "sceneLabel": item.scene_label,
        "title": item.scene_label,
        "difficultyLabel": item.difficulty_label,
        "completedCount": item.completed,
        "target": item.target,
        "progress": f"{item.completed}/{item.target}",
        "accuracy": f"{item.accuracy * 100:.0f}%",
        "duration": _duration_text(item.duration_seconds),
        "completed": item.completed_state,
        "date": (
            _relative_date(item.updated_at, relative_to)
            if relative_to is not None
            else _display_date(item.updated_at)
        ),
        "createdAt": item.created_at,
        "updatedAt": item.updated_at,
        "tag": _session_tag(item),
    }


def _summary_to_qml(summary: LearningSummary) -> dict[str, object]:
    return {
        "totalCompleted": summary.total_completed,
        "uniquePracticed": summary.unique_practiced,
        "accuracy": summary.accuracy,
        "accuracyText": f"{summary.accuracy * 100:.1f}%",
        "currentStreakDays": summary.current_streak_days,
        "longestStreakDays": summary.longest_streak_days,
        "totalDurationSeconds": summary.total_duration_seconds,
        "durationHours": round(summary.total_duration_seconds / 3600, 1),
        "pending": summary.pending,
    }


def _session_tag(item: SessionSummary) -> str:
    if "四级" in item.scene_label:
        return "CET-4"
    if "六级" in item.scene_label:
        return "CET-6"
    if item.practice_type is PracticeType.ENDLESS:
        return "∞"
    if item.practice_type is PracticeType.WRONG_REVIEW:
        return "错题"
    return "练习"


def _duration_text(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} 秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, remaining_minutes = divmod(minutes, 60)
    return f"{hours} 小时 {remaining_minutes} 分"


def _display_date(value: str) -> str:
    return value[:10] if value else "—"


def _relative_date(value: str, local_date: date) -> str:
    if not value:
        return "—"
    try:
        item_date = date.fromisoformat(value[:10])
    except ValueError:
        return _display_date(value)
    difference = (local_date - item_date).days
    if difference == 0:
        return "今天"
    if difference == 1:
        return "昨天"
    if 1 < difference <= 30:
        return f"{difference} 天前"
    return item_date.isoformat()


def _empty_dashboard() -> dict[str, object]:
    return {
        "resume": {
            "available": False,
            "sessionId": "",
            "title": "开始第一次练习",
            "subtitle": "START",
            "completed": 0,
            "target": 0,
            "progress": 0.0,
            "mode": "quantitative",
        },
        "dailyGoal": {
            "target": 30,
            "completed": 0,
            "remaining": 30,
            "percent": 0.0,
            "completedState": False,
        },
        "pending": {
            "total": 0,
            "vocabularyCount": 0,
            "phraseCount": 0,
            "confusingCount": 0,
        },
        "recentSessions": [],
        "trend7Days": [],
        "summary": _summary_to_qml(
            LearningSummary(0, 0, 0.0, 0, 0, 0, 0)
        ),
    }


def _empty_statistics() -> dict[str, object]:
    return {
        "range": "7d",
        "trend": [],
        "summary": _summary_to_qml(
            LearningSummary(0, 0, 0.0, 0, 0, 0, 0)
        ),
        "sceneDistribution": [],
        "difficultyDistribution": [],
    }
