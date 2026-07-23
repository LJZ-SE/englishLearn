from __future__ import annotations

import random
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

from listening_cloze.domain.feedback import FeedbackKind, FeedbackSelector
from listening_cloze.domain.models import Difficulty, Question, SceneSelection
from listening_cloze.domain.selection import QuestionProgress as SelectionProgress
from listening_cloze.domain.selection import QuestionSelector
from listening_cloze.domain.session import EndlessDifficultyState, QuestionAttempt
from listening_cloze.infrastructure.database import ContentQuestion, SceneMetadata, SessionRecord


class SceneCatalogUnavailableError(RuntimeError):
    """旧内容源尚未提供场景目录能力。"""


class ContentSource(Protocol):
    def list_scenes(self) -> list[SceneMetadata]: ...

    def sample_questions(
        self,
        *,
        top_scene: str | None,
        sub_scene: str | None,
        difficulty: str,
        limit: int,
        exclude_ids: frozenset[str],
        seed: int,
    ) -> list[ContentQuestion]: ...

    def get_questions_by_ids(
        self,
        ids: list[str] | tuple[str, ...],
    ) -> list[ContentQuestion]: ...


class UserStore(Protocol):
    def record_attempt(self, question_id: str, *, is_correct: bool): ...

    def record_replay(self, question_id: str): ...

    def record_view_answer(self, question_id: str): ...

    def save_session(
        self,
        session_id: str,
        *,
        mode: str,
        state: dict[str, object],
        completed: bool = False,
    ) -> SessionRecord: ...

    def complete_session(self, session_id: str) -> SessionRecord: ...

    def load_unfinished_session(self, *, mode: str | None = None) -> SessionRecord | None: ...

    def list_question_progress(self): ...

    def get_setting(self, key: str, default=None): ...

    def set_setting(self, key: str, value) -> None: ...

    def reset_learning_records(self) -> None: ...

    def get_learning_summary(self) -> dict[str, object]: ...


class PracticeMode(StrEnum):
    QUANTITATIVE = "quantitative"
    ENDLESS = "endless"


LEGACY_SCENE_MAP: dict[str, str] = {
    "daily": "daily",
    "exam": "study",
    "movies": "culture",
    "news_podcasts": "news",
}


@dataclass(frozen=True, slots=True)
class PracticeItem:
    question: Question
    answer_start: int
    answer_end: int

    @property
    def prefix(self) -> str:
        return self.question.sentence[: self.answer_start]

    @property
    def suffix(self) -> str:
        return self.question.sentence[self.answer_end :]

    @property
    def blank_count(self) -> int:
        return self.question.blank_count


@dataclass(slots=True)
class PracticeStats:
    completed: int = 0
    correct: int = 0
    wrong: int = 0
    viewed_answers: int = 0
    replays: int = 0
    longest_correct_streak: int = 0
    current_correct_streak: int = 0
    highest_difficulty: Difficulty = Difficulty.EASY


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    is_correct: bool
    counted_correct: bool
    mascot_kind: str
    feedback_text: str
    feedback_animation: str
    difficulty_changed: bool


class PracticeEngine:
    def __init__(
        self,
        content: ContentSource,
        users: UserStore,
        *,
        rng: random.Random | None = None,
    ) -> None:
        self._content = content
        self._users = users
        self._rng = rng or random.Random()
        self._selector = QuestionSelector(rng=self._rng)
        self._feedback = FeedbackSelector(rng=self._rng)
        self.mode: PracticeMode | None = None
        self.items: list[PracticeItem] = []
        self.position = 0
        self.stats = PracticeStats()
        self.endless_state: EndlessDifficultyState | None = None
        self._attempt: QuestionAttempt | None = None
        self._can_advance = False
        self._session_id = ""
        self._scene = SceneSelection(None, None)
        self._target_count: int | None = None
        self._queue_needs_rebuild = False
        self._outcomes: list[str] = []

    @property
    def current(self) -> PracticeItem:
        if not self.items:
            raise RuntimeError("练习尚未开始")
        return self.items[self.position]

    @property
    def prefetch_window(self) -> tuple[PracticeItem, ...]:
        return tuple(self.items[self.position : self.position + 3])

    @property
    def can_advance(self) -> bool:
        return self._can_advance

    @property
    def scene(self) -> SceneSelection:
        return self._scene

    def list_scenes(self) -> list[SceneMetadata]:
        provider = getattr(self._content, "list_scenes", None)
        if not callable(provider):
            raise SceneCatalogUnavailableError("内容源不支持场景目录")
        return list(provider())

    @property
    def has_unfinished_session(self) -> bool:
        return self._users.load_unfinished_session() is not None

    @property
    def has_review_items(self) -> bool:
        return self.mode is PracticeMode.QUANTITATIVE and "wrong" in self._outcomes

    @property
    def progress_states(self) -> list[str]:
        if self.mode is PracticeMode.QUANTITATIVE:
            target = self._target_count or len(self.items)
            states = list(self._outcomes)
            states.extend("pending" for _index in range(max(0, target - len(states))))
            if self.items and self.position < len(states) and self.position >= len(self._outcomes):
                states[self.position] = "current"
            start = self.progress_start
            return states[start : start + 10]
        if self.mode is PracticeMode.ENDLESS:
            states = list(self._outcomes)
            if self._attempt is not None and self._attempt.first_result is None:
                states.append("current")
            return states[-10:]
        return []

    @property
    def progress_start(self) -> int:
        if self.mode is PracticeMode.QUANTITATIVE:
            target = self._target_count or len(self.items)
            return max(0, min(self.position - 4, max(0, target - 10)))
        if self.mode is PracticeMode.ENDLESS:
            has_current = self._attempt is not None and self._attempt.first_result is None
            full_count = len(self._outcomes) + int(has_current)
            return max(0, full_count - min(10, full_count))
        return 0

    def start_quantitative(
        self,
        *,
        scene: SceneSelection | None = None,
        category: str | None = None,
        difficulty: Difficulty,
        count: int,
    ) -> None:
        if count not in {10, 20, 30} and count != 1 and count != 5:
            raise ValueError("定量练习题数必须为 10、20 或 30")
        selected_scene = self._resolve_scene(scene=scene, category=category)
        candidates = self._sample_questions(
            scene=selected_scene,
            difficulty=difficulty.value,
            limit=max(count * 3, 30),
            exclude_ids=frozenset(),
        )
        if len(candidates) < count:
            raise ValueError(f"题库只有 {len(candidates)} 道符合条件的题，无法开始 {count} 题练习")
        self._reset(PracticeMode.QUANTITATIVE, selected_scene)
        self._target_count = count
        self.items = self._select_unique(candidates, count)
        self._begin_current()
        self._save_session()

    def start_endless(
        self,
        *,
        scene: SceneSelection | None = None,
        category: str | None = None,
    ) -> None:
        self._reset(
            PracticeMode.ENDLESS,
            self._resolve_scene(scene=scene, category=category),
        )
        self.endless_state = EndlessDifficultyState.new_session()
        self._fill_endless_queue()
        self._begin_current()
        self._save_session()

    def start_review(self) -> None:
        review_items = [
            self.items[index]
            for index, outcome in enumerate(self._outcomes)
            if outcome == "wrong" and index < len(self.items)
        ]
        if not review_items:
            raise RuntimeError("本轮没有需要复习的题目")
        self.end_session()
        self._reset(PracticeMode.QUANTITATIVE, self._scene)
        self._target_count = len(review_items)
        self.items = review_items
        self._begin_current()
        self._save_session()

    def resume_latest(self) -> bool:
        record = self._users.load_unfinished_session()
        if record is None:
            return False
        state = record.state
        question_ids = [str(question_id) for question_id in state.get("question_ids", [])]
        restored_questions = self._content.get_questions_by_ids(question_ids)
        if not question_ids or [raw.id for raw in restored_questions] != question_ids:
            return False

        self.mode = PracticeMode(record.mode)
        self.items = [self._to_domain(raw) for raw in restored_questions]
        saved_position = max(0, min(int(state.get("position", 0)), len(self.items) - 1))
        self.position = saved_position
        self._session_id = record.session_id
        self._scene = self._scene_from_state(state)
        raw_target = state.get("target_count")
        self._target_count = int(raw_target) if raw_target is not None else None
        raw_stats = state.get("stats", {})
        self.stats = PracticeStats(
            completed=int(raw_stats.get("completed", 0)),
            correct=int(raw_stats.get("correct", 0)),
            wrong=int(raw_stats.get("wrong", 0)),
            viewed_answers=int(raw_stats.get("viewed_answers", 0)),
            replays=int(raw_stats.get("replays", 0)),
            longest_correct_streak=int(raw_stats.get("longest_correct_streak", 0)),
            current_correct_streak=int(raw_stats.get("current_correct_streak", 0)),
            highest_difficulty=Difficulty(raw_stats.get("highest_difficulty", "easy")),
        )
        self._outcomes = [str(value) for value in state.get("outcomes", [])]
        if self.mode is PracticeMode.ENDLESS:
            self.endless_state = EndlessDifficultyState(
                difficulty=Difficulty(state.get("difficulty", "easy")),
                correct_streak=int(state.get("correct_streak", 0)),
                incorrect_streak=int(state.get("incorrect_streak", 0)),
            )
        else:
            self.endless_state = None
        self._queue_needs_rebuild = bool(state.get("queue_needs_rebuild", False))
        if self.mode is PracticeMode.ENDLESS:
            self.items = self.items[saved_position : saved_position + 3]
            self.position = 0
            if not self._queue_needs_rebuild:
                self._fill_endless_queue()
        self._restore_attempt(state.get("attempt", {}))
        return True

    def submit(self, inputs: Sequence[str]) -> SubmissionResult:
        attempt = self._require_attempt()
        is_first = attempt.first_result is None
        previous_difficulty = (
            self.endless_state.difficulty if self.endless_state is not None else None
        )
        feedback = attempt.submit(inputs)
        self._users.record_attempt(self.current.question.id, is_correct=feedback.is_correct)

        if is_first:
            self._record_first_outcome(feedback.counted_correct)

        difficulty_changed = (
            previous_difficulty is not None
            and self.endless_state is not None
            and previous_difficulty is not self.endless_state.difficulty
        )
        if difficulty_changed:
            self._queue_needs_rebuild = True

        if difficulty_changed:
            assert previous_difficulty is not None
            assert self.endless_state is not None
            kind = (
                FeedbackKind.LEVEL_UP
                if list(Difficulty).index(self.endless_state.difficulty)
                > list(Difficulty).index(previous_difficulty)
                else FeedbackKind.LEVEL_DOWN
            )
        else:
            kind = FeedbackKind.CORRECT if feedback.is_correct else FeedbackKind.INCORRECT
        mascot = self._feedback.next(kind)
        self._can_advance = feedback.is_correct
        self._save_session()
        return SubmissionResult(
            is_correct=feedback.is_correct,
            counted_correct=feedback.counted_correct,
            mascot_kind=kind.value,
            feedback_text=mascot.text,
            feedback_animation=mascot.animation,
            difficulty_changed=difficulty_changed,
        )

    def reveal_answer(self) -> str:
        attempt = self._require_attempt()
        is_first = attempt.first_result is None
        already_revealed = attempt.answer_revealed
        answer = attempt.reveal_answer()
        if not already_revealed:
            self._users.record_view_answer(self.current.question.id)
            self.stats.viewed_answers += 1
        if is_first:
            self._record_first_outcome(False)
        self._can_advance = True
        self._save_session()
        return answer

    def record_replay(self) -> None:
        self._users.record_replay(self.current.question.id)
        self.stats.replays += 1
        self._save_session()

    def skip_current_for_audio_error(self) -> None:
        if not self.items:
            raise RuntimeError("练习尚未开始")
        current = self.current
        blocked_ids = frozenset(item.question.id for item in self.items)
        candidates = self._sample_questions(
            scene=self._scene,
            difficulty=current.question.difficulty.value,
            limit=30,
            exclude_ids=blocked_ids,
        )
        available = list(candidates)
        if not available:
            raise RuntimeError("没有可替换的同场景、同难度题目")
        replacement = self._select_unique(available, 1)[0]
        self.items[self.position] = replacement
        self._begin_current()
        self._save_session()

    def get_setting(self, key: str, default=None):
        return self._users.get_setting(key, default)

    def set_setting(self, key: str, value) -> None:
        self._users.set_setting(key, value)

    def reset_learning_records(self) -> None:
        self._users.reset_learning_records()
        self.mode = None
        self.items = []
        self.position = 0
        self.stats = PracticeStats()
        self.endless_state = None
        self._attempt = None
        self._session_id = ""
        self._outcomes = []

    def learning_summary(self) -> dict[str, object]:
        return self._users.get_learning_summary()

    def next_question(self) -> bool:
        if not self._can_advance:
            raise RuntimeError("答对或查看答案后才能进入下一题")
        if self.mode is PracticeMode.QUANTITATIVE:
            if self.position + 1 >= len(self.items):
                self._users.complete_session(self._session_id)
                return False
            self.position += 1
        else:
            if self._queue_needs_rebuild:
                self.items = []
                self.position = 0
                self._queue_needs_rebuild = False
            else:
                self.items = self.items[1:]
                self.position = 0
            self._fill_endless_queue()

        self._begin_current()
        self._save_session()
        return True

    def end_session(self) -> None:
        if self._session_id:
            self._users.complete_session(self._session_id)

    def _reset(self, mode: PracticeMode, scene: SceneSelection | str) -> None:
        self.mode = mode
        self.items = []
        self.position = 0
        self.stats = PracticeStats()
        self.endless_state = None
        self._attempt = None
        self._can_advance = False
        self._session_id = uuid.uuid4().hex
        self._scene = (
            scene
            if isinstance(scene, SceneSelection)
            else self._scene_from_legacy_category(scene)
        )
        self._target_count = None
        self._queue_needs_rebuild = False
        self._outcomes = []

    def _select_unique(
        self,
        candidates: Sequence[ContentQuestion],
        count: int,
    ) -> list[PracticeItem]:
        remaining = list(candidates)
        selected: list[PracticeItem] = []
        selection_history = self._selection_history()
        for _index in range(count):
            domain_candidates = [self._to_domain(item).question for item in remaining]
            chosen = self._selector.select(domain_candidates, selection_history)
            raw_index = next(index for index, item in enumerate(remaining) if item.id == chosen.id)
            selected.append(self._to_domain(remaining.pop(raw_index)))
        return selected

    def _fill_endless_queue(self) -> None:
        assert self.endless_state is not None
        active_items = self.items[self.position : self.position + 3]
        self.items = active_items
        self.position = 0
        missing = 3 - len(self.items)
        if missing <= 0:
            return
        active_ids = frozenset(item.question.id for item in self.items)
        candidates = self._sample_questions(
            scene=self._scene,
            difficulty=self.endless_state.difficulty.value,
            limit=max(missing * 3, 3),
            exclude_ids=active_ids,
        )
        if len(candidates) < missing:
            raise ValueError(
                "题库只有 "
                f"{len(candidates)} 道可用的 {self._scene_label()}/"
                f"{self.endless_state.difficulty.value} 题目，无法补足三题窗口"
            )
        self.items.extend(self._select_unique(candidates, missing))

    def _begin_current(self) -> None:
        self._attempt = QuestionAttempt(self.current.question)
        self._can_advance = False

    def _record_first_outcome(self, is_correct: bool) -> None:
        self.stats.completed += 1
        if is_correct:
            self.stats.correct += 1
            self.stats.current_correct_streak += 1
            self.stats.longest_correct_streak = max(
                self.stats.longest_correct_streak,
                self.stats.current_correct_streak,
            )
        else:
            self.stats.wrong += 1
            self.stats.current_correct_streak = 0
        self._outcomes.append("correct" if is_correct else "wrong")

        if self.endless_state is not None:
            self.endless_state.record_outcome(is_correct=is_correct)
            self.stats.highest_difficulty = max(
                self.stats.highest_difficulty,
                self.endless_state.difficulty,
                key=lambda level: list(Difficulty).index(level),
            )

    def _save_session(self) -> None:
        if not self._session_id or self.mode is None:
            return
        state: dict[str, object] = {
            "question_ids": [item.question.id for item in self.items],
            "position": self.position,
            "top_scene": self._scene.top_scene,
            "sub_scene": self._scene.sub_scene,
            "target_count": self._target_count,
            "outcomes": list(self._outcomes),
            "queue_needs_rebuild": self._queue_needs_rebuild,
            "stats": {
                **asdict(self.stats),
                "highest_difficulty": self.stats.highest_difficulty.value,
            },
        }
        if self.endless_state is not None:
            state["difficulty"] = self.endless_state.difficulty.value
            state["correct_streak"] = self.endless_state.correct_streak
            state["incorrect_streak"] = self.endless_state.incorrect_streak
        if self._attempt is not None:
            state["attempt"] = {
                "first_result": self._attempt.first_result,
                "submission_count": self._attempt.submission_count,
                "answer_revealed": self._attempt.answer_revealed,
                "can_advance": self._can_advance,
            }
        self._users.save_session(
            self._session_id,
            mode=self.mode.value,
            state=state,
        )

    def _require_attempt(self) -> QuestionAttempt:
        if self._attempt is None:
            raise RuntimeError("练习尚未开始")
        return self._attempt

    def _restore_attempt(self, raw_attempt: object) -> None:
        values = raw_attempt if isinstance(raw_attempt, dict) else {}
        self._attempt = QuestionAttempt(self.current.question)
        first_result = values.get("first_result")
        self._attempt.first_result = first_result if isinstance(first_result, bool) else None
        self._attempt.submission_count = int(values.get("submission_count", 0))
        self._attempt.answer_revealed = bool(values.get("answer_revealed", False))
        self._can_advance = bool(values.get("can_advance", False))

    def _selection_history(self) -> dict[str, SelectionProgress]:
        return {
            progress.question_id: SelectionProgress(
                first_result=progress.first_correct,
                answer_revealed=progress.view_answer_count > 0,
            )
            for progress in self._users.list_question_progress()
        }

    def _sample_questions(
        self,
        *,
        scene: SceneSelection,
        difficulty: str,
        limit: int,
        exclude_ids: frozenset[str],
    ) -> list[ContentQuestion]:
        return self._content.sample_questions(
            top_scene=scene.top_scene,
            sub_scene=scene.sub_scene,
            difficulty=difficulty,
            limit=limit,
            exclude_ids=exclude_ids,
            seed=self._rng.randrange(1 << 63),
        )

    @staticmethod
    def _resolve_scene(
        *,
        scene: SceneSelection | None,
        category: str | None,
    ) -> SceneSelection:
        if scene is not None and category is not None:
            raise ValueError("不能同时指定 scene 和旧 category")
        if scene is not None:
            return scene
        return PracticeEngine._scene_from_legacy_category(category or "all")

    @staticmethod
    def _scene_from_legacy_category(category: str) -> SceneSelection:
        if category == "all":
            return SceneSelection(None, None)
        return SceneSelection(LEGACY_SCENE_MAP.get(category, category), None)

    @staticmethod
    def _scene_from_state(state: dict[str, object]) -> SceneSelection:
        if "top_scene" in state or "sub_scene" in state:
            top_scene = state.get("top_scene")
            sub_scene = state.get("sub_scene")
            return SceneSelection(
                str(top_scene) if top_scene is not None else None,
                str(sub_scene) if sub_scene is not None else None,
            )
        return PracticeEngine._scene_from_legacy_category(
            str(state.get("category", "all"))
        )

    def _scene_label(self) -> str:
        if self._scene.sub_scene is not None:
            return self._scene.sub_scene
        return self._scene.top_scene or "all"

    @staticmethod
    def _to_domain(raw: ContentQuestion) -> PracticeItem:
        question = Question(
            id=raw.id,
            source_sentence_id=raw.sentence_id,
            sentence=raw.sentence_text,
            top_scene=raw.top_scene or raw.category,
            sub_scene=raw.sub_scene or None,
            difficulty=Difficulty(raw.difficulty),
            canonical_answer=raw.canonical_answer,
            equivalent_answers=raw.aliases,
            translation_zh=raw.translation_zh,
        )
        return PracticeItem(
            question=question,
            answer_start=raw.answer_start,
            answer_end=raw.answer_end,
        )
