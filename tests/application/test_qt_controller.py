import random
import sqlite3
import wave
from pathlib import Path

from PySide6.QtTest import QSignalSpy

from listening_cloze.application.controller import PracticeController
from listening_cloze.application.practice_engine import PracticeEngine
from listening_cloze.domain.models import SceneSelection
from listening_cloze.infrastructure.database import (
    ContentQuestion,
    ContentRepository,
    SceneMetadata,
    UserRepository,
)
from listening_cloze.infrastructure.tts_service import PrefetchItem


class FakeContentRepository:
    def __init__(
        self,
        questions: list[ContentQuestion],
        scenes: list[SceneMetadata] | None = None,
    ) -> None:
        self.questions = questions
        self.scenes = scenes if scenes is not None else _scene_catalog()

    def list_scenes(self) -> list[SceneMetadata]:
        return list(self.scenes)

    def list_questions(
        self,
        *,
        category: str | None = None,
        difficulty: str | None = None,
    ) -> list[ContentQuestion]:
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
        candidates = [
            question
            for question in self.questions
            if (top_scene is None or (question.top_scene or question.category) == top_scene)
            and (sub_scene is None or question.sub_scene == sub_scene)
            and question.difficulty == difficulty
            and question.id not in exclude_ids
        ]
        random.Random(seed).shuffle(candidates)
        return candidates[:limit]

    def get_questions_by_ids(self, ids: list[str] | tuple[str, ...]) -> list[ContentQuestion]:
        by_id = {question.id: question for question in self.questions}
        return [by_id[question_id] for question_id in ids if question_id in by_id]


class FakeTtsService:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.windows: list[list[PrefetchItem]] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def schedule(self, items) -> None:
        self.windows.append(list(items))


def test_controller_exposes_multi_blank_question_and_preserves_first_result(
    tmp_path: Path,
) -> None:
    engine = PracticeEngine(
        FakeContentRepository([_question("q1", "take part in")]),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(1),
    )
    controller = PracticeController(engine)

    controller.startQuantitative("daily", "easy", 1)

    assert controller.currentPage == "practice"
    assert controller.sentencePrefix == "You should "
    assert controller.sentenceSuffix == " today."
    assert controller.blankCount == 3
    assert controller.progressText == "第 1 / 1 题"

    controller.submitAnswers(["take", "part", "on"])
    assert controller.feedbackState == "incorrect"
    assert controller.wrongCount == 1
    assert not controller.canAdvance

    controller.submitAnswers(["take", "part", "in"])
    assert controller.feedbackState == "correct"
    assert controller.wrongCount == 1
    assert controller.correctCount == 0
    assert controller.canAdvance

    controller.nextQuestion()
    assert controller.currentPage == "summary"


def test_controller_category_label_uses_database_scene_label(tmp_path: Path) -> None:
    question = _question(
        "travel-question",
        "check in",
        top_scene="travel",
        sub_scene="travel_hotel",
    )
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository([question]),
            UserRepository(tmp_path / "user.db"),
            rng=random.Random(27),
        )
    )

    controller.startQuantitative("travel", "easy", 1)

    assert controller.categoryLabel == "出行旅行 / 酒店住宿"


def test_controller_exposes_database_scene_catalog_and_persists_selection(
    tmp_path: Path,
) -> None:
    database = tmp_path / "user.db"
    first = PracticeController(
        PracticeEngine(
            FakeContentRepository([]),
            UserRepository(database),
            rng=random.Random(30),
        )
    )
    state_changed = QSignalSpy(first.stateChanged)
    selection_changed = QSignalSpy(first.sceneSelectionChanged)
    label_changed = QSignalSpy(first.sceneLabelChanged)

    assert len(first.sceneCatalog) == 8
    assert sum(len(scene["children"]) for scene in first.sceneCatalog) == 32
    first.setScene("travel", "travel_hotel")

    assert first.selectedTopScene == "travel"
    assert first.selectedSubScene == "travel_hotel"
    assert first.sceneLabel == "出行旅行 / 酒店住宿"
    assert state_changed.count() == 1
    assert selection_changed.count() == 1
    assert label_changed.count() == 1

    restarted = PracticeController(
        PracticeEngine(
            FakeContentRepository([]),
            UserRepository(database),
            rng=random.Random(31),
        )
    )
    assert restarted.selectedTopScene == "travel"
    assert restarted.selectedSubScene == "travel_hotel"


def test_controller_repairs_invalid_or_cross_category_saved_scene(
    tmp_path: Path,
) -> None:
    database = tmp_path / "user.db"
    users = UserRepository(database)
    users.set_setting("selected_top_scene", "travel")
    users.set_setting("selected_sub_scene", "study_exam")

    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository([]),
            UserRepository(database),
            rng=random.Random(32),
        )
    )

    assert controller.selectedTopScene == "daily"
    assert controller.selectedSubScene == ""
    assert controller.sceneLabel == "日常生活"
    assert users.get_setting("selected_top_scene") == "daily"
    assert users.get_setting("selected_sub_scene") is None

    users.set_setting("selected_top_scene", "missing")
    users.set_setting("selected_sub_scene", None)
    repaired_again = PracticeController(
        PracticeEngine(
            FakeContentRepository([]),
            UserRepository(database),
            rng=random.Random(33),
        )
    )
    assert repaired_again.selectedTopScene == "daily"


def test_controller_falls_back_to_first_database_scene_when_daily_is_absent(
    tmp_path: Path,
) -> None:
    scenes = [
        SceneMetadata(
            key="travel",
            label="出行旅行",
            children=(SceneMetadata(key="travel_hotel", label="酒店住宿"),),
        )
    ]
    database = tmp_path / "user.db"
    users = UserRepository(database)
    users.set_setting("selected_top_scene", "missing")

    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository([], scenes),
            UserRepository(database),
            rng=random.Random(34),
        )
    )

    assert controller.selectedTopScene == "travel"
    assert controller.selectedSubScene == ""
    assert controller.sceneLabel == "出行旅行"
    assert users.get_setting("selected_top_scene") == "travel"


def test_controller_rejects_scene_not_owned_by_selected_top_category(
    tmp_path: Path,
) -> None:
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository([]),
            UserRepository(tmp_path / "user.db"),
            rng=random.Random(35),
        )
    )

    try:
        controller.setScene("travel", "study_exam")
    except ValueError as error:
        assert "场景" in str(error)
    else:
        raise AssertionError("跨大类子场景必须被拒绝")


def test_hierarchical_start_slots_pass_scene_selection_to_engine(tmp_path: Path) -> None:
    questions = [
        _question(
            f"travel-{index}",
            "check in",
            top_scene="travel",
            sub_scene="travel_hotel",
        )
        for index in range(3)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(36),
    )
    controller = PracticeController(engine)

    controller.startQuantitative("travel", "travel_hotel", "easy", 1)
    assert engine.scene == SceneSelection("travel", "travel_hotel")

    controller.startEndless("travel", "travel_hotel")
    assert engine.scene == SceneSelection("travel", "travel_hotel")


def test_legacy_qml_start_signatures_remain_compatible(tmp_path: Path) -> None:
    questions = [_question(f"q{index}", "listen") for index in range(8)]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(37),
    )
    controller = PracticeController(engine)

    controller.startQuantitative("daily", "easy", 1)
    assert engine.scene == SceneSelection("daily", None)

    controller.startEndless("daily")
    assert engine.scene == SceneSelection("daily", None)

    class CataloglessRepository(FakeContentRepository):
        list_scenes = None

    catalogless_engine = PracticeEngine(
        CataloglessRepository(questions),
        UserRepository(tmp_path / "catalogless-user.db"),
        rng=random.Random(38),
    )
    catalogless = PracticeController(catalogless_engine)
    catalogless.startQuantitative("daily", "easy", 1)
    assert catalogless_engine.scene == SceneSelection("daily", None)


def test_catalogless_legacy_compatibility_rejects_unknown_scene_and_does_not_persist(
    tmp_path: Path,
) -> None:
    class CataloglessRepository(FakeContentRepository):
        list_scenes = None

    database = tmp_path / "user.db"
    users = UserRepository(database)
    question = _question(
        "news-question",
        "listen",
        top_scene="news",
        sub_scene="news_current",
    )
    controller = PracticeController(
        PracticeEngine(
            CataloglessRepository([question]),
            users,
            rng=random.Random(39),
        )
    )

    controller.startQuantitative("news_podcasts", "easy", 1)
    assert users.get_setting("selected_top_scene") is None
    assert users.get_setting("selected_sub_scene") is None

    try:
        controller.startQuantitative("unknown", "easy", 1)
    except ValueError as error:
        assert "场景" in str(error)
    else:
        raise AssertionError("无目录兼容入口必须拒绝未知场景")


def test_failed_start_does_not_persist_requested_scene(tmp_path: Path) -> None:
    users = UserRepository(tmp_path / "user.db")
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository([]),
            users,
            rng=random.Random(40),
        )
    )

    try:
        controller.startQuantitative("travel", "travel_hotel", "easy", 1)
    except ValueError as error:
        assert "题库" in str(error)
    else:
        raise AssertionError("空题库必须拒绝启动")

    assert controller.selectedTopScene == "daily"
    assert controller.selectedSubScene == ""
    assert users.get_setting("selected_top_scene") == "daily"
    assert users.get_setting("selected_sub_scene") is None


def test_controller_reveals_answer_and_full_sentence_translation(tmp_path: Path) -> None:
    engine = PracticeEngine(
        FakeContentRepository([_question("q1", "do not", ("don't",), "我不会伤害你。")]),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(2),
    )
    controller = PracticeController(engine)
    controller.startQuantitative("daily", "easy", 1)
    revealed = QSignalSpy(controller.answerRevealed)

    controller.revealAnswer()

    assert revealed.count() == 1
    assert revealed.at(0)[0] == ["do", "not"]
    assert controller.feedbackState == "revealed"
    assert controller.sentenceTranslation == "我不会伤害你。"
    assert controller.viewedAnswerCount == 1
    assert controller.canAdvance


def test_initial_play_does_not_count_as_replay_but_replay_does(tmp_path: Path) -> None:
    engine = PracticeEngine(
        FakeContentRepository([_question("q1", "listen")]),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(3),
    )
    controller = PracticeController(engine)
    controller.startQuantitative("daily", "easy", 1)
    requested = QSignalSpy(controller.audioRequested)

    controller.play()
    controller.replay()

    assert requested.count() == 2
    assert requested.at(0) == ["q1", 1.0]
    assert controller.replayCount == 1


def test_each_new_question_requests_automatic_audio_without_counting_a_replay(
    tmp_path: Path,
) -> None:
    questions = [_question(f"q{index}", "listen") for index in range(8)]
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository(questions),
            UserRepository(tmp_path / "user.db"),
            rng=random.Random(25),
        )
    )
    requested = QSignalSpy(controller.audioRequested)

    controller.startQuantitative("daily", "easy", 5)

    assert requested.count() == 1
    assert controller.replayCount == 0

    controller.submitAnswers(["listen"])
    controller.nextQuestion()

    assert requested.count() == 2
    assert controller.replayCount == 0


def test_automatic_audio_waits_until_local_tts_is_ready(tmp_path: Path) -> None:
    engine = PracticeEngine(
        FakeContentRepository([_question("q1", "listen")]),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(26),
    )
    controller = PracticeController(engine)
    controller.attachTts(FakeTtsService())
    requested = QSignalSpy(controller.audioRequested)

    controller.startQuantitative("daily", "easy", 1)

    assert requested.count() == 0
    audio_file = tmp_path / "automatic.wav"
    with wave.open(str(audio_file), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44_100)
        output.writeframes(b"\x00\x00" * 40)
    controller.handleTtsReady(
        PrefetchItem("q1", engine.current.question.sentence),
        audio_file,
    )

    assert requested.count() == 1
    assert controller.replayCount == 0


def test_controller_schedules_current_and_next_two_and_publishes_ready_audio(
    tmp_path: Path,
) -> None:
    questions = [_question(f"q{index}", f"word{index}") for index in range(5)]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(4),
    )
    controller = PracticeController(engine)
    tts = FakeTtsService()
    controller.attachTts(tts)

    controller.startQuantitative("daily", "easy", 5)

    assert tts.started
    assert len(tts.windows[-1]) == 3
    current_id = controller.currentQuestionId
    audio_file = tmp_path / "current.wav"
    with wave.open(str(audio_file), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44_100)
        output.writeframes((b"\x00\x00" * 40) + (b"\xff\x3f" * 40))
    controller.handleTtsReady(
        PrefetchItem(current_id, engine.current.question.sentence), audio_file
    )

    assert controller.audioStatus == "ready"
    assert controller.audioSource == audio_file.resolve().as_uri()
    assert len(controller.waveformLevels) == 72
    assert max(controller.waveformLevels) == 1.0
    assert controller.audioDurationMs > 0


def test_playback_rate_reschedules_current_and_next_two_at_selected_speed(
    tmp_path: Path,
) -> None:
    questions = [_question(f"q{index}", f"word{index}") for index in range(5)]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(21),
    )
    controller = PracticeController(engine)
    tts = FakeTtsService()
    controller.attachTts(tts)
    controller.startQuantitative("daily", "easy", 5)

    controller.setPlaybackRate(0.8)

    assert len(tts.windows[-1]) == 3
    assert {item.playback_rate for item in tts.windows[-1]} == {0.8}


def test_startup_asset_issues_open_repair_page(tmp_path: Path) -> None:
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository([]),
            UserRepository(tmp_path / "user.db"),
            rng=random.Random(5),
        )
    )

    controller.setStartupIssues(["缺少题库 content.db", "缺少 Supertonic 模型"])

    assert controller.currentPage == "repair"
    assert controller.repairIssues == ["缺少题库 content.db", "缺少 Supertonic 模型"]


def test_missing_content_database_records_repair_issue_during_controller_init(
    tmp_path: Path,
) -> None:
    user_db = tmp_path / "user.db"
    users = UserRepository(user_db)
    users.set_setting("selected_top_scene", "travel")
    users.set_setting("selected_sub_scene", "travel_hotel")
    user_db_before = user_db.read_bytes()
    controller = PracticeController(
        PracticeEngine(
            ContentRepository(tmp_path / "missing-content.db"),
            users,
        )
    )

    assert controller.currentPage == "repair"
    assert any("场景目录" in issue and "content.db" in issue for issue in controller.repairIssues)
    assert users.get_setting("selected_top_scene") == "travel"
    assert users.get_setting("selected_sub_scene") == "travel_hotel"
    assert user_db.read_bytes() == user_db_before

    controller.setStartupIssues(["缺少 Supertonic 模型"])
    controller.setStartupIssues(["缺少 Supertonic 模型"])
    assert any("场景目录" in issue for issue in controller.repairIssues)
    assert "缺少 Supertonic 模型" in controller.repairIssues
    assert controller.repairIssues.count("缺少 Supertonic 模型") == 1


def test_legacy_v1_content_database_records_actionable_repair_issue(
    tmp_path: Path,
) -> None:
    content_db = tmp_path / "legacy-v1.db"
    with sqlite3.connect(content_db) as connection:
        connection.execute("CREATE TABLE sentences(id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE question_variants(id TEXT PRIMARY KEY)")

    user_db = tmp_path / "user.db"
    users = UserRepository(user_db)
    users.set_setting("selected_top_scene", "travel")
    users.set_setting("selected_sub_scene", "travel_hotel")
    user_db_before = user_db.read_bytes()
    controller = PracticeController(
        PracticeEngine(
            ContentRepository(content_db),
            users,
        )
    )

    assert controller.currentPage == "repair"
    assert any("场景目录" in issue and "替换" in issue for issue in controller.repairIssues)
    assert users.get_setting("selected_top_scene") == "travel"
    assert users.get_setting("selected_sub_scene") == "travel_hotel"
    assert user_db.read_bytes() == user_db_before


def test_corrupt_content_database_preserves_scene_settings_while_opening_repair(
    tmp_path: Path,
) -> None:
    content_db = tmp_path / "corrupt-content.db"
    content_db.write_bytes(b"not a sqlite database")
    user_db = tmp_path / "user.db"
    users = UserRepository(user_db)
    users.set_setting("selected_top_scene", "travel")
    users.set_setting("selected_sub_scene", "travel_hotel")
    user_db_before = user_db.read_bytes()

    controller = PracticeController(
        PracticeEngine(ContentRepository(content_db), users)
    )

    assert controller.currentPage == "repair"
    assert any("场景目录" in issue for issue in controller.repairIssues)
    assert users.get_setting("selected_top_scene") == "travel"
    assert users.get_setting("selected_sub_scene") == "travel_hotel"
    assert user_db.read_bytes() == user_db_before


def test_formal_content_source_with_empty_scene_catalog_opens_repair_page(
    tmp_path: Path,
) -> None:
    users = UserRepository(tmp_path / "user.db")
    controller = PracticeController(
        PracticeEngine(FakeContentRepository([], scenes=[]), users)
    )

    assert controller.currentPage == "repair"
    assert any("场景目录为空" in issue for issue in controller.repairIssues)
    assert users.get_setting("selected_top_scene") is None
    assert users.get_setting("selected_sub_scene") is None


def test_formal_content_source_with_childless_scene_opens_repair_page(
    tmp_path: Path,
) -> None:
    scenes = [SceneMetadata(key="daily", label="日常生活", children=())]
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository([], scenes=scenes),
            UserRepository(tmp_path / "user.db"),
        )
    )

    assert controller.currentPage == "repair"
    assert any("结构不完整" in issue for issue in controller.repairIssues)


def test_nonempty_scene_catalog_does_not_report_repair_issue(tmp_path: Path) -> None:
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository([]),
            UserRepository(tmp_path / "user.db"),
        )
    )

    assert controller.currentPage == "home"
    assert controller.repairIssues == []


def test_controller_persists_settings_resume_progress_and_audio_skip(tmp_path: Path) -> None:
    questions = [_question(f"q{index}", "listen") for index in range(8)]
    database = tmp_path / "user.db"
    users = UserRepository(database)
    first_engine = PracticeEngine(
        FakeContentRepository(questions),
        users,
        rng=random.Random(14),
    )
    first = PracticeController(first_engine, audio_cache_dir=tmp_path / "cache")
    first.setPlaybackRate(0.8)
    first.setVolume(0.55)
    first.setAnimationsEnabled(False)
    first.startQuantitative("daily", "easy", 5)
    first.submitAnswers(["wrong"])

    second_engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(database),
        rng=random.Random(15),
    )
    second = PracticeController(second_engine, audio_cache_dir=tmp_path / "cache")

    assert second.hasResume
    assert second.playbackRate == 0.8
    assert second.volume == 0.55
    assert not second.animationsEnabled
    second.resumeLatest()
    assert second.currentPage == "practice"
    assert second.progressStates[0] == "wrong"

    failed_id = second.currentQuestionId
    second.handleTtsError(
        PrefetchItem(
            failed_id,
            second_engine.current.question.sentence,
            playback_rate=0.8,
        ),
        RuntimeError("模型故障"),
    )
    assert second.audioStatus == "error"
    second.skipAudioQuestion()
    assert second.currentQuestionId != failed_id
    assert second.wrongCount == 1


def test_returning_home_and_resuming_keeps_the_live_practice_state(tmp_path: Path) -> None:
    questions = [_question(f"q{index}", "listen") for index in range(8)]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(23),
    )
    controller = PracticeController(engine)
    controller.startQuantitative("daily", "easy", 5)
    controller.submitAnswers(["wrong"])
    current_question_id = controller.currentQuestionId

    controller.goHome()

    assert controller.currentPage == "home"
    assert controller.hasResume

    controller.resumeLatest()

    assert controller.currentPage == "practice"
    assert controller.currentQuestionId == current_question_id
    assert controller.feedbackState == "incorrect"
    assert controller.wrongCount == 1


def test_live_resume_restores_active_hierarchical_scene_after_home_selection_changes(
    tmp_path: Path,
) -> None:
    questions = [
        _question(
            f"hotel-{index}",
            "check in",
            top_scene="travel",
            sub_scene="travel_hotel",
        )
        for index in range(5)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(41),
    )
    controller = PracticeController(engine)
    controller.startQuantitative("travel", "travel_hotel", "easy", 5)
    controller.goHome()
    controller.setScene("daily", "")
    selection_changed = QSignalSpy(controller.sceneSelectionChanged)
    label_changed = QSignalSpy(controller.sceneLabelChanged)

    controller.resumeLatest()

    assert controller.currentPage == "practice"
    assert controller.selectedTopScene == "travel"
    assert controller.selectedSubScene == "travel_hotel"
    assert controller.sceneLabel == "出行旅行 / 酒店住宿"
    assert selection_changed.count() == 1
    assert label_changed.count() >= 1


def test_cold_resume_restores_hierarchical_scene_selection_and_label(
    tmp_path: Path,
) -> None:
    questions = [
        _question(
            f"hotel-{index}",
            "check in",
            top_scene="travel",
            sub_scene="travel_hotel",
        )
        for index in range(5)
    ]
    database = tmp_path / "user.db"
    first = PracticeController(
        PracticeEngine(
            FakeContentRepository(questions),
            UserRepository(database),
            rng=random.Random(42),
        )
    )
    first.startQuantitative("travel", "travel_hotel", "easy", 5)

    second_engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(database),
        rng=random.Random(43),
    )
    second = PracticeController(second_engine)
    second.setScene("daily", "")

    second.resumeLatest()

    assert second_engine.scene == SceneSelection("travel", "travel_hotel")
    assert second.selectedTopScene == "travel"
    assert second.selectedSubScene == "travel_hotel"
    assert second.sceneLabel == "出行旅行 / 酒店住宿"


def test_all_content_session_uses_active_scene_label_without_overwriting_selection(
    tmp_path: Path,
) -> None:
    users = UserRepository(tmp_path / "user.db")
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository([_question("q1", "listen")]),
            users,
            rng=random.Random(44),
        )
    )

    controller.startQuantitative("all", "easy", 1)

    assert controller.sceneLabel == "全部内容"
    assert controller.selectedTopScene == "daily"
    assert users.get_setting("selected_top_scene") == "daily"


def test_explicit_all_scene_selection_persists_and_drives_quantitative_session(
    tmp_path: Path,
) -> None:
    database = tmp_path / "user.db"
    users = UserRepository(database)
    engine = PracticeEngine(
        FakeContentRepository([_question("q-all", "listen")]),
        users,
        rng=random.Random(45),
    )
    controller = PracticeController(engine)

    controller.setScene("", "")

    assert controller.selectedTopScene == ""
    assert controller.selectedSubScene == ""
    assert controller.sceneLabel == "全部内容"
    assert users.get_setting("selected_top_scene") == ""
    assert users.get_setting("selected_sub_scene") is None

    controller.startQuantitative("", "", "easy", 1)

    assert engine.scene == SceneSelection(None, None)
    assert controller.currentPage == "practice"
    assert controller.sceneLabel == "全部内容"

    restarted = PracticeController(
        PracticeEngine(
            FakeContentRepository([]),
            UserRepository(database),
            rng=random.Random(46),
        )
    )
    assert restarted.selectedTopScene == ""
    assert restarted.selectedSubScene == ""
    assert restarted.sceneLabel == "全部内容"


def test_explicit_all_scene_drives_endless_without_resume_overwriting_home_choice(
    tmp_path: Path,
) -> None:
    questions = [_question(f"q-all-{index}", "listen") for index in range(3)]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(47),
    )
    controller = PracticeController(engine)

    controller.startEndless("", "")

    assert engine.scene == SceneSelection(None, None)
    assert controller.sceneLabel == "全部内容"
    controller.goHome()
    controller.setScene("daily", "")

    controller.resumeLatest()

    assert controller.currentPage == "practice"
    assert controller.selectedTopScene == "daily"
    assert controller.selectedSubScene == ""
    assert controller.sceneLabel == "全部内容"


def test_closing_settings_returns_to_the_page_that_opened_it(tmp_path: Path) -> None:
    questions = [_question(f"q{index}", "listen") for index in range(8)]
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository(questions),
            UserRepository(tmp_path / "user.db"),
            rng=random.Random(24),
        )
    )
    controller.startQuantitative("daily", "easy", 5)
    controller.submitAnswers(["wrong"])

    controller.openSettings()
    assert controller.currentPage == "settings"

    controller.closeSettings()
    assert controller.currentPage == "practice"
    assert controller.feedbackState == "incorrect"

    controller.goHome()
    controller.openSettings()
    controller.closeSettings()
    assert controller.currentPage == "home"


def test_reset_learning_records_requires_explicit_confirmation(tmp_path: Path) -> None:
    users = UserRepository(tmp_path / "user.db")
    users.record_attempt("q1", is_correct=False)
    engine = PracticeEngine(
        FakeContentRepository([_question("q1", "listen")]),
        users,
        rng=random.Random(16),
    )
    controller = PracticeController(engine)

    controller.resetLearningRecords(False)
    assert users.get_question_progress("q1") is not None

    controller.resetLearningRecords(True)
    assert users.get_question_progress("q1") is None


def test_endless_summary_exposes_adaptive_session_metrics(tmp_path: Path) -> None:
    engine = PracticeEngine(
        FakeContentRepository([_question(f"q{index}", "listen") for index in range(8)]),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(19),
    )
    controller = PracticeController(engine)
    controller.startEndless("daily")
    controller.submitAnswers(["listen"])

    controller.endSession()

    assert controller.currentPage == "summary"
    assert controller.isEndlessSummary
    assert controller.completedCount == 1
    assert controller.accuracyText == "100%"
    assert controller.highestDifficultyLabel == "简单"
    assert controller.endingDifficultyLabel == "简单"
    assert controller.longestStreak == 1


def _scene_catalog() -> list[SceneMetadata]:
    definitions = [
        (
            "daily",
            "日常生活",
            ("daily_home", "家庭家务"),
            ("daily_social", "社交沟通"),
            ("daily_shopping", "购物服务"),
            ("daily_food", "餐饮烹饪"),
        ),
        (
            "travel",
            "出行旅行",
            ("travel_transport", "交通通勤"),
            ("travel_directions", "问路导航"),
            ("travel_hotel", "酒店住宿"),
            ("travel_tourism", "旅行观光"),
        ),
        (
            "work",
            "职场商务",
            ("work_office", "办公协作"),
            ("work_meetings", "会议演示"),
            ("work_contact", "邮件电话"),
            ("work_jobs", "求职面试"),
        ),
        (
            "study",
            "学习考试",
            ("study_campus", "校园课堂"),
            ("study_exams", "考试备考"),
            ("study_academic", "学术研究"),
            ("study_language", "语言学习"),
        ),
        (
            "health",
            "健康医疗",
            ("health_clinic", "医院就诊"),
            ("health_pharmacy", "药店用药"),
            ("health_fitness", "健身运动"),
            ("health_wellbeing", "身心健康"),
        ),
        (
            "technology",
            "科技科学",
            ("technology_devices", "数码设备"),
            ("technology_software", "互联网软件"),
            ("technology_engineering", "工程技术"),
            ("technology_science", "科学科普"),
        ),
        (
            "culture",
            "文化娱乐",
            ("culture_movies", "影视戏剧"),
            ("culture_music", "音乐艺术"),
            ("culture_books", "阅读文学"),
            ("culture_sports", "体育休闲"),
        ),
        (
            "news",
            "新闻社会",
            ("news_current", "时事新闻"),
            ("news_business", "财经商业"),
            ("news_public", "法律公共事务"),
            ("news_environment", "环境社会"),
        ),
    ]
    return [
        SceneMetadata(
            key=key,
            label=label,
            children=tuple(
                SceneMetadata(key=child_key, label=child_label)
                for child_key, child_label in children
            ),
        )
        for key, label, *children in definitions
    ]


def _question(
    question_id: str,
    answer: str,
    aliases: tuple[str, ...] = (),
    translation_zh: str = "",
    *,
    top_scene: str = "daily",
    sub_scene: str = "daily_home",
) -> ContentQuestion:
    sentence = f"You should {answer} today."
    start = sentence.index(answer)
    return ContentQuestion(
        id=question_id,
        sentence_id=f"sentence-{question_id}",
        sentence_text=sentence,
        translation_zh=translation_zh,
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
        rationale="测试数据",
        aliases=aliases,
    )
