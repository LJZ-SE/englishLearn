from __future__ import annotations

import sqlite3
import wave
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from listening_cloze.application.practice_engine import (
    PracticeEngine,
    PracticeMode,
    SceneCatalogUnavailableError,
)
from listening_cloze.domain.models import Difficulty, SceneSelection
from listening_cloze.infrastructure.tts_service import PrefetchItem, TtsPrefetchService
from listening_cloze.infrastructure.waveform import extract_waveform_levels

DIFFICULTY_LABELS = {
    Difficulty.EASY: "简单",
    Difficulty.MEDIUM: "中等",
    Difficulty.HARD: "困难",
}
CATEGORY_LABELS = {
    "all": "全部内容",
    "daily": "日常口语",
    "exam": "考试英语",
    "movies": "影视表达",
    "news_podcasts": "新闻 / 播客",
}
LEGACY_SCENE_SELECTIONS = {
    "all": SceneSelection(None, None),
    "daily": SceneSelection("daily", None),
    "exam": SceneSelection("study", None),
    "movies": SceneSelection("culture", None),
    "news_podcasts": SceneSelection("news", None),
}


class SceneCatalogInvalidError(RuntimeError):
    """正式题库提供了无法使用的场景目录。"""


class PracticeController(QObject):
    stateChanged = Signal()
    questionChanged = Signal()
    sceneCatalogChanged = Signal()
    sceneSelectionChanged = Signal()
    sceneLabelChanged = Signal()
    answerRevealed = Signal(list)
    audioRequested = Signal(str, float)
    _ttsReady = Signal(object, str)
    _ttsFailed = Signal(object, str)

    def __init__(
        self,
        engine: PracticeEngine,
        parent: QObject | None = None,
        *,
        audio_cache_dir: str | Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._current_page = "home"
        self._settings_return_page = "home"
        self._repair_issues: list[str] = []
        self._feedback_state = "idle"
        self._feedback_text = "准备好后，播放句子开始练习。"
        self._feedback_animation = "idle"
        try:
            self._scene_catalog = self._load_scene_catalog()
        except (OSError, sqlite3.Error, SceneCatalogInvalidError) as error:
            self._scene_catalog = []
            self._repair_issues.append(
                f"题库 content.db 场景目录无法读取，请修复或替换题库：{error}"
            )
            self._current_page = "repair"
        self._scene_by_key = {scene["key"]: scene for scene in self._scene_catalog}
        self._selected_top_scene, self._selected_sub_scene = self._load_scene_selection()
        self._active_scene: SceneSelection | None = None
        self._playback_rate = float(engine.get_setting("playback_rate", 1.0))
        self._volume = float(engine.get_setting("volume", 0.8))
        self._animations_enabled = bool(engine.get_setting("animations_enabled", True))
        self._audio_cache_dir = Path(audio_cache_dir) if audio_cache_dir is not None else None
        self._tts: TtsPrefetchService | None = None
        self._ready_audio: dict[tuple[str, float], Path] = {}
        self._audio_status = "idle"
        self._audio_source = ""
        self._audio_error = ""
        self._waveform_levels: list[float] = []
        self._audio_duration_ms = 0
        self._play_when_ready = False
        self._ttsReady.connect(self._apply_tts_ready)
        self._ttsFailed.connect(self._apply_tts_error)

    @Property(str, notify=stateChanged)
    def currentPage(self) -> str:
        return self._current_page

    @Property(str, notify=stateChanged)
    def sentencePrefix(self) -> str:
        return self._engine.current.prefix if self._engine.items else ""

    @Property(str, notify=stateChanged)
    def sentenceSuffix(self) -> str:
        return self._engine.current.suffix if self._engine.items else ""

    @Property(str, notify=stateChanged)
    def sentenceTranslation(self) -> str:
        return self._engine.current.question.translation_zh if self._engine.items else ""

    @Property(int, notify=stateChanged)
    def blankCount(self) -> int:
        return self._engine.current.blank_count if self._engine.items else 0

    @Property(str, notify=stateChanged)
    def progressText(self) -> str:
        if not self._engine.items:
            return ""
        if self._engine.mode is PracticeMode.ENDLESS:
            return f"第 {self._engine.stats.completed + 1} 题 · 无尽模式"
        return f"第 {self._engine.position + 1} / {len(self._engine.items)} 题"

    @Property(str, notify=stateChanged)
    def difficulty(self) -> str:
        if not self._engine.items:
            return Difficulty.EASY.value
        return self._engine.current.question.difficulty.value

    @Property(str, notify=stateChanged)
    def difficultyLabel(self) -> str:
        if not self._engine.items:
            return DIFFICULTY_LABELS[Difficulty.EASY]
        return DIFFICULTY_LABELS[self._engine.current.question.difficulty]

    @Property(list, notify=sceneCatalogChanged)
    def sceneCatalog(self) -> list[dict[str, object]]:
        return [
            {
                "key": scene["key"],
                "label": scene["label"],
                "children": [dict(child) for child in scene["children"]],
            }
            for scene in self._scene_catalog
        ]

    @Property(str, notify=sceneSelectionChanged)
    def selectedTopScene(self) -> str:
        return self._selected_top_scene

    @Property(str, notify=sceneSelectionChanged)
    def selectedSubScene(self) -> str:
        return self._selected_sub_scene or ""

    @Property(str, notify=sceneLabelChanged)
    def sceneLabel(self) -> str:
        if self._current_page in {"practice", "summary"} and self._active_scene is not None:
            return self._label_for_scene(
                self._active_scene.top_scene or "",
                self._active_scene.sub_scene,
            )
        return self._label_for_scene(self._selected_top_scene, self._selected_sub_scene)

    @Property(str, notify=stateChanged)
    def categoryLabel(self) -> str:
        if not self._engine.items:
            return self.sceneLabel
        question = self._engine.current.question
        top_scene = str(question.top_scene or question.category.value)
        return self._label_for_scene(
            top_scene,
            str(question.sub_scene) if question.sub_scene else None,
        )

    @Property(str, notify=stateChanged)
    def feedbackState(self) -> str:
        return self._feedback_state

    @Property(str, notify=stateChanged)
    def feedbackText(self) -> str:
        return self._feedback_text

    @Property(str, notify=stateChanged)
    def feedbackAnimation(self) -> str:
        return self._feedback_animation

    @Property(bool, notify=stateChanged)
    def canAdvance(self) -> bool:
        return self._engine.can_advance

    @Property(int, notify=stateChanged)
    def correctCount(self) -> int:
        return self._engine.stats.correct

    @Property(int, notify=stateChanged)
    def wrongCount(self) -> int:
        return self._engine.stats.wrong

    @Property(int, notify=stateChanged)
    def viewedAnswerCount(self) -> int:
        return self._engine.stats.viewed_answers

    @Property(int, notify=stateChanged)
    def replayCount(self) -> int:
        return self._engine.stats.replays

    @Property(float, notify=stateChanged)
    def playbackRate(self) -> float:
        return self._playback_rate

    @Property(float, notify=stateChanged)
    def volume(self) -> float:
        return self._volume

    @Property(bool, notify=stateChanged)
    def animationsEnabled(self) -> bool:
        return self._animations_enabled

    @Property(bool, notify=stateChanged)
    def hasResume(self) -> bool:
        return self._engine.has_unfinished_session

    @Property(list, notify=stateChanged)
    def progressStates(self) -> list[str]:
        return self._engine.progress_states

    @Property(int, notify=stateChanged)
    def progressStart(self) -> int:
        return self._engine.progress_start

    @Property(str, notify=stateChanged)
    def cacheSummary(self) -> str:
        if self._audio_cache_dir is None or not self._audio_cache_dir.exists():
            return "0 个文件 · 0 MB"
        files = list(self._audio_cache_dir.glob("*.wav"))
        total_bytes = sum(path.stat().st_size for path in files if path.is_file())
        return f"{len(files)} 个文件 · {total_bytes / (1024 * 1024):.1f} MB"

    @Property(int, notify=stateChanged)
    def practicedCount(self) -> int:
        return int(self._engine.learning_summary()["practiced"])

    @Property(int, notify=stateChanged)
    def pendingCount(self) -> int:
        return int(self._engine.learning_summary()["pending"])

    @Property(str, notify=stateChanged)
    def recentPracticeText(self) -> str:
        summary = self._engine.learning_summary()
        mode = summary["latest_mode"]
        if mode is None:
            return "还没有练习记录"
        label = "无尽模式" if mode == "endless" else "定量练习"
        status = "已完成" if summary["latest_completed"] else "未完成"
        return f"{label} · {status}"

    @Property(bool, notify=stateChanged)
    def hasReviewItems(self) -> bool:
        return self._engine.has_review_items

    @Property(bool, notify=stateChanged)
    def isEndlessSummary(self) -> bool:
        return self._engine.mode is PracticeMode.ENDLESS

    @Property(int, notify=stateChanged)
    def completedCount(self) -> int:
        return self._engine.stats.completed

    @Property(str, notify=stateChanged)
    def accuracyText(self) -> str:
        completed = self._engine.stats.completed
        percentage = 0 if completed == 0 else round(self._engine.stats.correct / completed * 100)
        return f"{percentage}%"

    @Property(str, notify=stateChanged)
    def highestDifficultyLabel(self) -> str:
        return DIFFICULTY_LABELS[self._engine.stats.highest_difficulty]

    @Property(str, notify=stateChanged)
    def endingDifficultyLabel(self) -> str:
        state = self._engine.endless_state
        return DIFFICULTY_LABELS[state.difficulty] if state is not None else "—"

    @Property(int, notify=stateChanged)
    def longestStreak(self) -> int:
        return self._engine.stats.longest_correct_streak

    @Property(str, notify=stateChanged)
    def currentQuestionId(self) -> str:
        return self._engine.current.question.id if self._engine.items else ""

    @Property(str, notify=stateChanged)
    def audioStatus(self) -> str:
        return self._audio_status

    @Property(str, notify=stateChanged)
    def audioSource(self) -> str:
        return self._audio_source

    @Property(str, notify=stateChanged)
    def audioError(self) -> str:
        return self._audio_error

    @Property(list, notify=stateChanged)
    def waveformLevels(self) -> list[float]:
        return list(self._waveform_levels)

    @Property(int, notify=stateChanged)
    def audioDurationMs(self) -> int:
        return self._audio_duration_ms

    @Property(list, notify=stateChanged)
    def repairIssues(self) -> list[str]:
        return list(self._repair_issues)

    def setStartupIssues(self, issues: list[str]) -> None:
        self._repair_issues.extend(issue for issue in issues if issue not in self._repair_issues)
        if self._repair_issues:
            self._current_page = "repair"
        self.stateChanged.emit()

    def attachTts(self, service: TtsPrefetchService) -> None:
        if self._tts is not None:
            self._tts.stop()
        self._tts = service
        self._tts.start()

    def handleTtsReady(self, item: PrefetchItem, path: Path) -> None:
        self._ttsReady.emit(item, str(path.resolve()))

    def handleTtsError(self, item: PrefetchItem, error: Exception) -> None:
        self._ttsFailed.emit(item, str(error))

    @Slot(str, str, int)
    @Slot(str, str, str, int)
    def startQuantitative(
        self,
        top_scene: str,
        sub_scene_or_difficulty: str,
        difficulty_or_count: str | int,
        count: int | None = None,
    ) -> None:
        if count is None:
            scene = self._legacy_scene_selection(top_scene)
            difficulty = sub_scene_or_difficulty
            resolved_count = int(difficulty_or_count)
        else:
            scene = self._validated_scene_selection(top_scene, sub_scene_or_difficulty)
            difficulty = str(difficulty_or_count)
            resolved_count = count
        self._engine.start_quantitative(
            scene=scene,
            difficulty=Difficulty(difficulty),
            count=resolved_count,
        )
        self._remember_scene_if_selectable(scene)
        self._begin_practice_page()

    @Slot(str)
    @Slot(str, str)
    def startEndless(self, top_scene: str = "all", sub_scene: str | None = None) -> None:
        if sub_scene is None:
            scene = self._legacy_scene_selection(top_scene)
        else:
            scene = self._validated_scene_selection(top_scene, sub_scene)
        self._engine.start_endless(scene=scene)
        self._remember_scene_if_selectable(scene)
        self._begin_practice_page()

    @Slot(str, str)
    def setScene(self, top_scene: str, sub_scene: str | None = None) -> None:
        self._remember_scene_if_selectable(self._validated_scene_selection(top_scene, sub_scene))

    @Slot()
    def resumeLatest(self) -> None:
        if (
            self._current_page == "home"
            and self._engine.items
            and self._engine.has_unfinished_session
        ):
            self._current_page = "practice"
            self._sync_scene_from_engine()
            self.stateChanged.emit()
            self.sceneLabelChanged.emit()
            return
        if self._engine.resume_latest():
            self._begin_practice_page()

    @Slot()
    def reviewWrongQuestions(self) -> None:
        self._engine.start_review()
        self._begin_practice_page()

    @Slot("QVariantList")
    def submitAnswers(self, inputs: list[str]) -> None:
        result = self._engine.submit(inputs)
        self._feedback_state = result.mascot_kind
        self._feedback_text = result.feedback_text
        self._feedback_animation = result.feedback_animation
        self.stateChanged.emit()

    @Slot()
    def revealAnswer(self) -> None:
        answer = self._engine.reveal_answer()
        self._feedback_state = "revealed"
        self._feedback_text = f"答案是：{answer}"
        self._feedback_animation = "droop"
        self.answerRevealed.emit(answer.split())
        self.stateChanged.emit()

    @Slot()
    def nextQuestion(self) -> None:
        question_changed = self._engine.next_question()
        if question_changed:
            self._feedback_state = "idle"
            self._feedback_text = "仔细听完整句子，再补全空位。"
            self._feedback_animation = "idle"
            self._reset_audio_state()
            self._schedule_audio()
        else:
            self._current_page = "summary"
        self.stateChanged.emit()
        if question_changed:
            self.questionChanged.emit()
            self._request_automatic_playback()

    @Slot()
    def play(self) -> None:
        question_id = self._engine.current.question.id
        audio_key = (question_id, self._playback_rate)
        if self._tts is None or audio_key in self._ready_audio:
            self._set_current_audio_source()
            self.audioRequested.emit(question_id, self._playback_rate)
            return
        self._play_when_ready = True
        self._audio_status = "loading"
        self._schedule_audio()
        self.stateChanged.emit()

    @Slot()
    def replay(self) -> None:
        self._engine.record_replay()
        self.play()

    @Slot(float)
    def setPlaybackRate(self, rate: float) -> None:
        if rate not in {0.8, 1.0, 1.2}:
            raise ValueError("播放语速只能是 0.8、1.0 或 1.2")
        self._playback_rate = rate
        self._engine.set_setting("playback_rate", rate)
        if self._current_page == "practice" and self._engine.items:
            self._reset_audio_state()
            self._schedule_audio()
        self.stateChanged.emit()

    @Slot(float)
    def setVolume(self, volume: float) -> None:
        self._volume = max(0.0, min(float(volume), 1.0))
        self._engine.set_setting("volume", self._volume)
        self.stateChanged.emit()

    @Slot(bool)
    def setAnimationsEnabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        self._engine.set_setting("animations_enabled", enabled)
        self.stateChanged.emit()

    @Slot()
    def goHome(self) -> None:
        self._current_page = "home"
        self.stateChanged.emit()
        self.sceneLabelChanged.emit()

    @Slot()
    def openSettings(self) -> None:
        if self._current_page != "settings":
            self._settings_return_page = self._current_page
        self._current_page = "settings"
        self.stateChanged.emit()

    @Slot()
    def closeSettings(self) -> None:
        self._current_page = self._settings_return_page
        self.stateChanged.emit()

    @Slot()
    def endSession(self) -> None:
        self._engine.end_session()
        self._current_page = "summary"
        self.stateChanged.emit()

    @Slot()
    def retryAudio(self) -> None:
        self._audio_status = "loading"
        self._audio_error = ""
        self._play_when_ready = True
        self._schedule_audio()
        self.stateChanged.emit()

    @Slot()
    def skipAudioQuestion(self) -> None:
        if self._audio_status != "error":
            return
        self._engine.skip_current_for_audio_error()
        self._feedback_state = "idle"
        self._feedback_text = "已跳过音频故障题，本题不计成绩。"
        self._feedback_animation = "idle"
        self._reset_audio_state()
        self._schedule_audio()
        self.stateChanged.emit()
        self.questionChanged.emit()
        self._request_automatic_playback()

    @Slot(bool)
    def resetLearningRecords(self, confirmed: bool) -> None:
        if not confirmed:
            return
        self._engine.reset_learning_records()
        self._current_page = "home"
        self.stateChanged.emit()

    @Slot()
    def shutdown(self) -> None:
        if self._tts is not None:
            self._tts.stop()

    def _load_scene_catalog(self) -> list[dict[str, object]]:
        try:
            scene_metadata = self._engine.list_scenes()
        except SceneCatalogUnavailableError:
            return []
        if not scene_metadata:
            raise SceneCatalogInvalidError("题库场景目录为空，请替换完整题库")

        catalog: list[dict[str, object]] = []
        top_keys: set[str] = set()
        child_keys: set[str] = set()
        for top_scene in scene_metadata:
            top_key = str(top_scene.key)
            top_label = str(top_scene.label)
            raw_children = tuple(top_scene.children)
            if not top_key or not top_label or top_key in top_keys or not raw_children:
                raise SceneCatalogInvalidError("题库场景目录结构不完整，请替换完整题库")
            top_keys.add(top_key)
            children = [
                {"key": str(child.key), "label": str(child.label)}
                for child in raw_children
            ]
            if any(
                not child["key"]
                or not child["label"]
                or child["key"] in child_keys
                for child in children
            ):
                raise SceneCatalogInvalidError("题库场景目录结构不完整，请替换完整题库")
            child_keys.update(str(child["key"]) for child in children)
            catalog.append({"key": top_key, "label": top_label, "children": children})
        return catalog

    def _load_scene_selection(self) -> tuple[str, str | None]:
        missing = object()
        stored_top = self._engine.get_setting("selected_top_scene", missing)
        stored_sub = self._engine.get_setting("selected_sub_scene", missing)
        top_scene = stored_top if isinstance(stored_top, str) else ""
        sub_scene = stored_sub if stored_sub is None or isinstance(stored_sub, str) else ""
        valid = bool(top_scene) and self._is_valid_scene(top_scene, sub_scene)

        if valid:
            selected = (top_scene, sub_scene)
        else:
            fallback = "daily" if "daily" in self._scene_by_key else ""
            if not fallback and self._scene_catalog:
                fallback = str(self._scene_catalog[0]["key"])
            selected = (fallback or "daily", None)

        if self._scene_catalog and (
            stored_top != selected[0] or stored_sub != selected[1]
        ):
            self._engine.set_setting("selected_top_scene", selected[0])
            self._engine.set_setting("selected_sub_scene", selected[1])
        return selected

    def _is_valid_scene(self, top_scene: str, sub_scene: str | None) -> bool:
        top_entry = self._scene_by_key.get(top_scene)
        if top_entry is None:
            return False
        if sub_scene is None:
            return True
        return any(
            child["key"] == sub_scene for child in top_entry["children"] if isinstance(child, dict)
        )

    def _validated_scene_selection(
        self,
        top_scene: str,
        sub_scene: str | None,
    ) -> SceneSelection:
        normalized_sub_scene = sub_scene or None
        if not self._is_valid_scene(top_scene, normalized_sub_scene):
            raise ValueError("所选场景不存在或不属于当前大类")
        return SceneSelection(top_scene, normalized_sub_scene)

    def _legacy_scene_selection(self, category: str) -> SceneSelection:
        mapped = LEGACY_SCENE_SELECTIONS.get(category)
        if mapped is not None:
            if mapped.top_scene is None or not self._scene_catalog:
                return mapped
            return self._validated_scene_selection(mapped.top_scene, None)
        if not self._scene_catalog:
            raise ValueError("无场景目录时只支持旧版内置分类")
        return self._validated_scene_selection(category, None)

    def _remember_scene_if_selectable(self, scene: SceneSelection) -> None:
        if scene.top_scene is None or not self._is_valid_scene(scene.top_scene, scene.sub_scene):
            return
        if (
            scene.top_scene == self._selected_top_scene
            and scene.sub_scene == self._selected_sub_scene
        ):
            return
        self._selected_top_scene = scene.top_scene
        self._selected_sub_scene = scene.sub_scene
        self._engine.set_setting("selected_top_scene", scene.top_scene)
        self._engine.set_setting("selected_sub_scene", scene.sub_scene)
        self.sceneSelectionChanged.emit()
        self.sceneLabelChanged.emit()
        self.stateChanged.emit()

    def _label_for_scene(self, top_scene: str, sub_scene: str | None) -> str:
        top_entry = self._scene_by_key.get(top_scene)
        if top_entry is None:
            return CATEGORY_LABELS.get(top_scene, top_scene or CATEGORY_LABELS["all"])
        top_label = str(top_entry["label"])
        if sub_scene is None:
            return top_label
        for child in top_entry["children"]:
            if isinstance(child, dict) and child["key"] == sub_scene:
                return f"{top_label} / {child['label']}"
        return top_label

    def _sync_scene_from_engine(self) -> None:
        self._active_scene = self._engine.scene
        self._remember_scene_if_selectable(self._active_scene)

    def _begin_practice_page(self) -> None:
        self._current_page = "practice"
        self._sync_scene_from_engine()
        self._feedback_state = "idle"
        self._feedback_text = "仔细听完整句子，再补全空位。"
        self._feedback_animation = "idle"
        self._reset_audio_state()
        self._schedule_audio()
        self.stateChanged.emit()
        self.sceneLabelChanged.emit()
        self.questionChanged.emit()
        self._request_automatic_playback()

    def _request_automatic_playback(self) -> None:
        if not self._engine.items:
            return
        question_id = self._engine.current.question.id
        audio_key = (question_id, self._playback_rate)
        if self._tts is None or audio_key in self._ready_audio:
            self._set_current_audio_source()
            self.audioRequested.emit(question_id, self._playback_rate)
            return
        self._play_when_ready = True

    def _schedule_audio(self) -> None:
        if self._tts is None or not self._engine.items:
            return
        self._tts.schedule(
            [
                PrefetchItem(
                    item.question.id,
                    item.question.sentence,
                    playback_rate=self._playback_rate,
                )
                for item in self._engine.prefetch_window
            ]
        )
        current_id = self._engine.current.question.id
        if (current_id, self._playback_rate) not in self._ready_audio:
            self._audio_status = "loading"

    def _reset_audio_state(self) -> None:
        self._audio_source = ""
        self._audio_error = ""
        self._waveform_levels = []
        self._audio_duration_ms = 0
        self._audio_status = "idle" if self._tts is None else "loading"
        self._play_when_ready = False
        self._set_current_audio_source()

    def _set_current_audio_source(self) -> None:
        if not self._engine.items:
            return
        path = self._ready_audio.get((self._engine.current.question.id, self._playback_rate))
        if path is not None:
            self._audio_source = path.as_uri()
            try:
                self._waveform_levels = extract_waveform_levels(path)
                with wave.open(str(path), "rb") as audio:
                    self._audio_duration_ms = round(
                        audio.getnframes() / audio.getframerate() * 1000
                    )
            except (OSError, ValueError, wave.Error):
                self._waveform_levels = []
                self._audio_duration_ms = 0
            self._audio_status = "ready"

    @Slot(object, str)
    def _apply_tts_ready(self, item: PrefetchItem, path_text: str) -> None:
        self._ready_audio[(item.question_id, item.playback_rate)] = Path(path_text)
        if item.question_id == self.currentQuestionId and item.playback_rate == self._playback_rate:
            self._set_current_audio_source()
            should_play = self._play_when_ready
            self._play_when_ready = False
            self.stateChanged.emit()
            if should_play:
                self.audioRequested.emit(item.question_id, self._playback_rate)

    @Slot(object, str)
    def _apply_tts_error(self, item: PrefetchItem, error: str) -> None:
        if item.question_id != self.currentQuestionId or item.playback_rate != self._playback_rate:
            return
        self._audio_status = "error"
        self._audio_error = error
        self._play_when_ready = False
        self.stateChanged.emit()
