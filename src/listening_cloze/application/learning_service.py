from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from listening_cloze.application.learning_contracts import (
    DAILY_GOALS,
    DailyGoalSummary,
    DashboardSnapshot,
    DistributionItem,
    HistoryFilter,
    LearningSummary,
    PageResult,
    PendingSummary,
    PracticeType,
    ResumeSummary,
    SceneFilterItem,
    SessionSummary,
    StatisticsSnapshot,
    TrendPoint,
    TrendRange,
    VocabularyItem,
    VocabularyReason,
    WrongQuestionItem,
)
from listening_cloze.infrastructure.database import (
    ContentQuestion,
    ContentRepository,
    QuestionProgress,
    SessionRecord,
    UserRepository,
)

MODE_LABELS = {
    PracticeType.QUANTITATIVE: "定量练习",
    PracticeType.ENDLESS: "无尽模式",
    PracticeType.WRONG_REVIEW: "错题复习",
    PracticeType.VOCABULARY_REVIEW: "词汇复习",
}
DIFFICULTY_LABELS = {
    "easy": "简单",
    "medium": "中等",
    "hard": "困难",
    "": "综合",
}


class LearningCenterService:
    def __init__(
        self,
        content: ContentRepository,
        users: UserRepository,
    ) -> None:
        self._content = content
        self._users = users
        self._top_labels: dict[str, str] = {}
        self._sub_labels: dict[str, tuple[str, str]] = {}
        self._load_scene_labels()

    def scene_filters(self) -> tuple[SceneFilterItem, ...]:
        return (
            SceneFilterItem(key="all", label="全部场景"),
            *(
                SceneFilterItem(key=key, label=label)
                for key, label in self._top_labels.items()
            ),
        )

    def dashboard(self, *, local_date: date) -> DashboardSnapshot:
        sessions = self._users.list_sessions()
        unfinished = next((session for session in sessions if not session.completed), None)
        pending_progress, pending_questions = self._pending_data()
        return DashboardSnapshot(
            resume=self._resume_summary(unfinished),
            daily_goal=self._daily_goal(local_date),
            pending=self._pending_summary(pending_progress, pending_questions),
            recent_sessions=tuple(
                self._session_summary(session) for session in sessions[:3]
            ),
            trend_7_days=self._trend(local_date=local_date, days=7),
            summary=self._learning_summary(
                local_date=local_date,
                pending=len(pending_progress),
            ),
        )

    def session_history(
        self,
        *,
        filter_key: HistoryFilter,
        offset: int,
        limit: int,
    ) -> PageResult[SessionSummary]:
        if offset < 0 or limit < 1:
            raise ValueError("学习记录分页参数无效")
        practice_type = None if filter_key is HistoryFilter.ALL else filter_key.value
        records = self._users.list_sessions(
            practice_type=practice_type,
            offset=offset,
            limit=limit + 1,
        )
        return PageResult(
            items=tuple(self._session_summary(record) for record in records[:limit]),
            has_more=len(records) > limit,
        )

    def wrong_questions(
        self,
        *,
        scene_key: str | None,
        search_text: str,
    ) -> tuple[WrongQuestionItem, ...]:
        progresses, questions = self._pending_data()
        question_by_id = {question.id: question for question in questions}
        normalized_search = search_text.casefold().strip()
        items: list[WrongQuestionItem] = []
        for progress in progresses:
            question = question_by_id.get(progress.question_id)
            if question is None:
                continue
            if scene_key and question.top_scene != scene_key:
                continue
            scene_label = self._scene_label(question.top_scene, question.sub_scene)
            if normalized_search and normalized_search not in " ".join(
                (
                    question.sentence_text,
                    question.translation_zh,
                    question.canonical_answer,
                    scene_label,
                )
            ).casefold():
                continue
            items.append(
                WrongQuestionItem(
                    question_id=question.id,
                    sentence=question.sentence_text,
                    translation=question.translation_zh,
                    answer=question.canonical_answer,
                    scene_label=scene_label,
                    review_correct_streak=progress.review_correct_streak,
                    required_review_streak=3,
                    first_wrong_at=progress.first_wrong_at or progress.updated_at,
                    updated_at=progress.updated_at,
                )
            )
        return tuple(items)

    def vocabulary(self, *, search_text: str) -> tuple[VocabularyItem, ...]:
        return tuple(
            VocabularyItem(
                entry_id=entry.entry_id,
                term=entry.term,
                sentence=entry.sentence,
                translation=entry.translation,
                source_question_id=entry.source_question_id,
                reason=VocabularyReason(entry.reason),
                encounter_count=entry.encounter_count,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
                source_kind=entry.source_kind,
            )
            for entry in self._users.list_vocabulary(search_text=search_text)
        )

    def statistics(
        self,
        *,
        range_key: TrendRange,
        local_date: date,
    ) -> StatisticsSnapshot:
        pending = len(self._users.list_pending_progress())
        days = 7 if range_key is TrendRange.DAYS_7 else 30
        sessions = self._users.list_sessions()
        return StatisticsSnapshot(
            daily_goal=self._daily_goal(local_date),
            range_key=range_key,
            trend=self._trend(local_date=local_date, days=days),
            summary=self._learning_summary(local_date=local_date, pending=pending),
            scene_distribution=self._session_distribution(
                sessions,
                key_getter=lambda session: session.top_scene or "all",
                label_getter=lambda key: self._top_labels.get(key, "全部场景"),
            ),
            difficulty_distribution=self._session_distribution(
                sessions,
                key_getter=lambda session: session.difficulty or "mixed",
                label_getter=lambda key: DIFFICULTY_LABELS.get(key, "综合"),
            ),
        )

    def set_daily_goal(self, target: int) -> None:
        if target not in DAILY_GOALS:
            raise ValueError("每日目标只支持 10、20、30 或 50 题")
        self._users.set_setting("daily_goal", target)

    def remove_vocabulary(self, entry_id: str) -> None:
        self._users.remove_vocabulary(entry_id)

    def mark_mastered(self, question_id: str) -> None:
        self._users.mark_mastered(question_id)

    def _load_scene_labels(self) -> None:
        try:
            scenes = self._content.list_scenes()
        except Exception:
            return
        for top_scene in scenes:
            self._top_labels[top_scene.key] = top_scene.label
            for child in top_scene.children:
                self._sub_labels[child.key] = (top_scene.label, child.label)

    def _resume_summary(self, record: SessionRecord | None) -> ResumeSummary:
        if record is None:
            return ResumeSummary(
                available=False,
                session_id="",
                title="开始第一次练习",
                subtitle="START",
                completed=0,
                target=0,
                progress=0.0,
                mode=PracticeType.QUANTITATIVE,
            )
        practice_type = self._practice_type(record)
        target = record.target_count or max(record.completed_count, 1)
        scene_label = self._scene_label(record.top_scene, record.sub_scene)
        return ResumeSummary(
            available=True,
            session_id=record.session_id,
            title=f"{scene_label} · {MODE_LABELS[practice_type]}",
            subtitle=self._scene_short_label(record.top_scene, record.sub_scene),
            completed=record.completed_count,
            target=target,
            progress=min(1.0, record.completed_count / target),
            mode=practice_type,
        )

    def _daily_goal(self, local_date: date) -> DailyGoalSummary:
        raw_target = int(self._users.get_setting("daily_goal", 30))
        target = raw_target if raw_target in DAILY_GOALS else 30
        activity = self._users.get_daily_activity(local_date.isoformat())
        completed = activity.completed_count if activity is not None else 0
        return DailyGoalSummary.build(target=target, completed=completed)

    def _pending_data(
        self,
    ) -> tuple[list[QuestionProgress], list[ContentQuestion]]:
        progresses = self._users.list_pending_progress()
        questions = self._content.get_questions_by_ids(
            [progress.question_id for progress in progresses]
        )
        return progresses, questions

    @staticmethod
    def _pending_summary(
        progresses: list[QuestionProgress],
        questions: list[ContentQuestion],
    ) -> PendingSummary:
        question_by_id = {question.id: question for question in questions}
        vocabulary_count = 0
        phrase_count = 0
        confusing_count = 0
        for progress in progresses:
            question = question_by_id.get(progress.question_id)
            if question is not None and question.answer_word_count > 1:
                phrase_count += 1
            elif (
                progress.view_answer_count > 0
                or progress.attempt_count > 1
                or question is None
            ):
                confusing_count += 1
            else:
                vocabulary_count += 1
        return PendingSummary(
            total=len(progresses),
            vocabulary_count=vocabulary_count,
            phrase_count=phrase_count,
            confusing_count=confusing_count,
        )

    def _session_summary(self, record: SessionRecord) -> SessionSummary:
        practice_type = self._practice_type(record)
        target = record.target_count or record.completed_count
        accuracy = (
            record.correct_count / record.completed_count
            if record.completed_count
            else 0.0
        )
        return SessionSummary(
            session_id=record.session_id,
            practice_type=practice_type,
            mode_label=MODE_LABELS[practice_type],
            scene_label=self._scene_label(record.top_scene, record.sub_scene),
            difficulty_label=DIFFICULTY_LABELS.get(record.difficulty, "综合"),
            completed=record.completed_count,
            target=target,
            accuracy=accuracy,
            duration_seconds=record.duration_seconds,
            completed_state=record.completed,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _trend(self, *, local_date: date, days: int) -> tuple[TrendPoint, ...]:
        start_date = local_date - timedelta(days=days - 1)
        by_date = {
            date.fromisoformat(activity.activity_date): activity.completed_count
            for activity in self._users.list_daily_activity(
                start_date=start_date.isoformat(),
                end_date=local_date.isoformat(),
            )
        }
        return tuple(
            TrendPoint(
                activity_date=day,
                label=day.strftime("%m/%d"),
                completed=by_date.get(day, 0),
            )
            for day in (
                start_date + timedelta(days=offset)
                for offset in range(days)
            )
        )

    def _learning_summary(
        self,
        *,
        local_date: date,
        pending: int,
    ) -> LearningSummary:
        activities = self._users.list_daily_activity()
        total_completed = sum(item.completed_count for item in activities)
        total_duration = sum(item.duration_seconds for item in activities)
        active_dates = {
            date.fromisoformat(item.activity_date)
            for item in activities
            if item.completed_count > 0
        }
        current_streak, longest_streak = _streaks(active_dates, local_date)
        practiced_progress = [
            progress
            for progress in self._users.list_question_progress()
            if progress.first_correct is not None
        ]
        unique_practiced = len(practiced_progress)
        first_result_correct = sum(
            progress.first_correct is True for progress in practiced_progress
        )
        return LearningSummary(
            total_completed=total_completed,
            unique_practiced=unique_practiced,
            accuracy=(
                first_result_correct / unique_practiced
                if unique_practiced
                else 0.0
            ),
            current_streak_days=current_streak,
            longest_streak_days=longest_streak,
            total_duration_seconds=total_duration,
            pending=pending,
        )

    def _session_distribution(
        self,
        sessions: list[SessionRecord],
        *,
        key_getter,
        label_getter,
    ) -> tuple[DistributionItem, ...]:
        counts: Counter[str] = Counter()
        for session in sessions:
            counts[key_getter(session)] += session.completed_count
        total = sum(counts.values())
        return tuple(
            DistributionItem(
                key=key,
                label=label_getter(key),
                count=count,
                percent=count / total if total else 0.0,
            )
            for key, count in counts.most_common()
        )

    @staticmethod
    def _practice_type(record: SessionRecord) -> PracticeType:
        try:
            return PracticeType(record.practice_type)
        except ValueError:
            return PracticeType(record.mode)

    def _scene_label(self, top_scene: str, sub_scene: str) -> str:
        if sub_scene in self._sub_labels:
            top_label, sub_label = self._sub_labels[sub_scene]
            return f"{top_label} · {sub_label}"
        return self._top_labels.get(top_scene, "全部场景")

    def _scene_short_label(self, top_scene: str, sub_scene: str) -> str:
        label = self._sub_labels.get(sub_scene, ("", ""))[1]
        if "四级" in label:
            return "CET-4"
        if "六级" in label:
            return "CET-6"
        return self._top_labels.get(top_scene, "练习")


def _streaks(active_dates: set[date], local_date: date) -> tuple[int, int]:
    if not active_dates:
        return 0, 0
    ordered = sorted(active_dates)
    longest = 1
    running = 1
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current - previous == timedelta(days=1):
            running += 1
            longest = max(longest, running)
        else:
            running = 1

    cursor = local_date if local_date in active_dates else local_date - timedelta(days=1)
    current = 0
    while cursor in active_dates:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest
