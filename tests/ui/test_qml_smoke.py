from dataclasses import replace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QObject, QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

from listening_cloze.application.controller import PracticeController
from listening_cloze.application.practice_engine import PracticeEngine
from listening_cloze.infrastructure.database import ContentQuestion, UserRepository
from listening_cloze.runtime import ui_path


@pytest.mark.qt_serial
def test_main_qml_loads_and_exposes_primary_practice_controls(qtbot) -> None:
    application = QApplication.instance() or QApplication([])
    assert application is not None
    engine = QQmlApplicationEngine()

    engine.load(ui_path("Main.qml"))

    assert len(engine.rootObjects()) == 1
    root = engine.rootObjects()[0]
    expected_names = {
        "homePage",
        "practicePage",
        "playButton",
        "backHomeButton",
        "replayShortcut",
        "audioToolbar",
        "speedSelector",
        "answerFields",
        "translationPanel",
        "submitButton",
        "mascot",
        "progressTrack",
        "repairPage",
        "resumeButton",
        "settingsDoneButton",
        "audioErrorPanel",
        "resetConfirmation",
    }
    actual_names = {child.objectName() for child in root.findChildren(QObject)}
    assert expected_names <= actual_names


def test_mascot_qml_implements_distinct_feedback_animations() -> None:
    source = ui_path("WaveMascot.qml").read_text(encoding="utf-8")

    for animation in (
        "bounce_wave",
        "clap",
        "spin",
        "stretch_wave",
        "confetti",
        "droop",
        "shake_head",
        "shrink_wave",
        "crouch",
        "sway",
        "level_up_rise",
        "level_down_soft",
    ):
        assert f'animationName === "{animation}"' in source


def test_practice_uses_audible_sound_effect_instead_of_silent_media_player() -> None:
    source = ui_path("PracticePage.qml").read_text(encoding="utf-8")

    assert "SoundEffect {" in source
    assert "MediaPlayer {" not in source


def test_practice_wraps_long_sentences_and_scales_the_waveform() -> None:
    source = ui_path("PracticePage.qml").read_text(encoding="utf-8")

    assert "Flow {" in source
    assert "wrapMode: Text.Wrap" in source
    assert "sentenceLength" in source
    assert "waveformScale" in source


def test_practice_shows_chinese_translation_after_reveal_or_correct_answer() -> None:
    source = ui_path("PracticePage.qml").read_text(encoding="utf-8")

    assert "中文翻译" in source
    assert 'page.visualCorrect || page.state === "revealed"' in source
    assert "sentenceTranslation" in source


@pytest.mark.qt_serial
def test_practice_layout_never_expands_beyond_the_window(tmp_path, qtbot) -> None:
    question = ContentQuestion(
        id="q-layout",
        sentence_id="s-layout",
        sentence_text="We wanted to talk about Tom.",
        category="daily",
        source_url="https://example.test/layout",
        normalized_hash="layout-hash",
        difficulty="hard",
        answer_start=13,
        answer_end=23,
        canonical_answer="talk about",
        answer_word_count=2,
        difficulty_score=3.0,
        rationale="布局回归测试",
        aliases=(),
        translation_zh="我们想谈谈汤姆。",
    )

    class SingleQuestionRepository:
        def list_questions(self, **_filters):
            return [question]

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            SingleQuestionRepository(),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "hard", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    root.setWidth(1984)
    root.setHeight(1278)
    for _ in range(10):
        QCoreApplication.processEvents()

    practice = root.findChild(QQuickItem, "practicePage")
    answer_fields = root.findChild(QQuickItem, "answerFields")
    audio_toolbar = root.findChild(QQuickItem, "audioToolbar")
    waveform = next(
        item
        for item in root.findChildren(QQuickItem)
        if item.metaObject().className().startswith("Waveform_")
    )

    assert practice is not None
    assert answer_fields is not None
    assert audio_toolbar is not None
    assert answer_fields.width() <= practice.width()
    assert audio_toolbar.width() <= 360
    assert waveform.width() <= practice.width()


@pytest.mark.qt_serial
def test_practice_clears_reused_answer_fields_when_question_changes(tmp_path, qtbot) -> None:
    questions = [
        ContentQuestion(
            id="q-one",
            sentence_id="s-one",
            sentence_text="We wanted to talk about Tom.",
            category="daily",
            source_url="https://example.test/one",
            normalized_hash="one-hash",
            difficulty="hard",
            answer_start=13,
            answer_end=23,
            canonical_answer="talk about",
            answer_word_count=2,
            difficulty_score=3.0,
            rationale="输入框复用测试",
            aliases=(),
        ),
        ContentQuestion(
            id="q-two",
            sentence_id="s-two",
            sentence_text="I promise I will never hurt you.",
            category="daily",
            source_url="https://example.test/two",
            normalized_hash="two-hash",
            difficulty="hard",
            answer_start=10,
            answer_end=19,
            canonical_answer="will never",
            answer_word_count=2,
            difficulty_score=3.0,
            rationale="输入框复用测试",
            aliases=(),
        ),
    ]
    questions.extend(
        replace(
            questions[0],
            id=f"q-extra-{index}",
            sentence_id=f"s-extra-{index}",
            normalized_hash=f"extra-hash-{index}",
        )
        for index in range(3)
    )

    class TwoQuestionRepository:
        def list_questions(self, **_filters):
            return questions

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            TwoQuestionRepository(),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "hard", 5)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    for _ in range(5):
        QCoreApplication.processEvents()

    answer_fields = root.findChild(QQuickItem, "answerFields")

    def visual_descendants(item):
        for child in item.childItems():
            yield child
            yield from visual_descendants(child)

    inputs = [
        item
        for item in visual_descendants(answer_fields)
        if item.objectName().startswith("answerInput")
    ]
    assert len(inputs) == 2

    controller.revealAnswer()
    QCoreApplication.processEvents()
    assert all(item.property("text") for item in inputs)

    controller.nextQuestion()
    QCoreApplication.processEvents()

    assert all(item.property("text") == "" for item in inputs)


@pytest.mark.qt_serial
def test_space_moves_focus_to_the_next_answer_field_without_being_entered(
    tmp_path, qtbot
) -> None:
    sentence = "They pass many experimental tests today."
    answer = "pass many experimental tests"
    question = ContentQuestion(
        id="q-space-focus",
        sentence_id="s-space-focus",
        sentence_text=sentence,
        category="daily",
        source_url="https://example.test/space-focus",
        normalized_hash="space-focus-hash",
        difficulty="hard",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=4,
        difficulty_score=3.0,
        rationale="空格切换输入框测试",
        aliases=(),
    )

    class SingleQuestionRepository:
        def list_questions(self, **_filters):
            return [question]

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            SingleQuestionRepository(),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "hard", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    for _ in range(5):
        QCoreApplication.processEvents()

    answer_fields = root.findChild(QQuickItem, "answerFields")

    def visual_descendants(item):
        for child in item.childItems():
            yield child
            yield from visual_descendants(child)

    inputs = sorted(
        (
            item
            for item in visual_descendants(answer_fields)
            if item.objectName().startswith("answerInput")
        ),
        key=lambda item: item.objectName(),
    )
    assert len(inputs) == 4

    inputs[0].forceActiveFocus()
    for key, text in ((Qt.Key_J, "j"), (Qt.Key_J, "j"), (Qt.Key_S, "s")):
        QCoreApplication.sendEvent(
            inputs[0], QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text)
        )
    QCoreApplication.sendEvent(
        inputs[0], QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " ")
    )
    QCoreApplication.processEvents()

    assert inputs[0].property("text") == "jjs"
    assert inputs[1].property("activeFocus") is True


@pytest.mark.qt_serial
def test_overflowing_practice_content_can_scroll_until_submit_button_is_visible(
    tmp_path, qtbot, qtlog
) -> None:
    sentence = (
        'Brown responded by saying that "a million people come from Europe, '
        'but a million people, British people, have gone into Europe."'
    )
    answer = "people come from Europe"
    question = ContentQuestion(
        id="q-scroll",
        sentence_id="s-scroll",
        sentence_text=sentence,
        category="news_podcasts",
        source_url="https://example.test/scroll",
        normalized_hash="scroll-hash",
        difficulty="hard",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=4,
        difficulty_score=3.0,
        rationale="练习内容滚动测试",
        aliases=(),
        translation_zh="布朗回应说，一百万人来自欧洲，但有一百万英国人进入了欧洲。",
    )

    class SingleQuestionRepository:
        def list_questions(self, **_filters):
            return [question]

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            SingleQuestionRepository(),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("news_podcasts", "hard", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    root.setWidth(1500)
    root.setHeight(760)
    controller.revealAnswer()
    for _ in range(10):
        QCoreApplication.processEvents()

    practice_scroll = root.findChild(QQuickItem, "practiceScroll")
    submit_button = root.findChild(QQuickItem, "submitButton")

    assert practice_scroll is not None
    assert submit_button is not None
    flickable = practice_scroll.property("contentItem")
    assert flickable.property("contentHeight") > flickable.height()

    maximum_y = flickable.property("contentHeight") - flickable.height()
    flickable.setProperty("contentY", maximum_y)
    QCoreApplication.processEvents()
    button_position = submit_button.mapToItem(practice_scroll, QPointF(0, 0))

    assert button_position.y() + submit_button.height() <= practice_scroll.height()
    assert not any("Binding loop" in record.message for record in qtlog.records)


@pytest.mark.qt_serial
def test_home_round_trip_keeps_the_unsubmitted_answer_draft(tmp_path, qtbot) -> None:
    sentence = "They pass many tests today."
    answer = "pass many"
    question = ContentQuestion(
        id="q-home-round-trip",
        sentence_id="s-home-round-trip",
        sentence_text=sentence,
        category="daily",
        source_url="https://example.test/home-round-trip",
        normalized_hash="home-round-trip-hash",
        difficulty="easy",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=2,
        difficulty_score=1.0,
        rationale="主页往返测试",
        aliases=(),
    )

    class SingleQuestionRepository:
        def list_questions(self, **_filters):
            return [question]

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            SingleQuestionRepository(),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "easy", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    for _ in range(5):
        QCoreApplication.processEvents()

    back_button = root.findChild(QQuickItem, "backHomeButton")
    resume_button = root.findChild(QQuickItem, "resumeButton")
    answer_fields = root.findChild(QQuickItem, "answerFields")

    def visual_descendants(item):
        for child in item.childItems():
            yield child
            yield from visual_descendants(child)

    first_input = next(
        item
        for item in visual_descendants(answer_fields)
        if item.objectName() == "answerInput0"
    )
    assert back_button is not None
    assert resume_button is not None
    first_input.setProperty("text", "draft")

    QMetaObject.invokeMethod(back_button, "click")
    QCoreApplication.processEvents()

    assert controller.currentPage == "home"
    assert resume_button.property("visible") is True

    QMetaObject.invokeMethod(resume_button, "click")
    QCoreApplication.processEvents()

    assert controller.currentPage == "practice"
    assert first_input.property("text") == "draft"


@pytest.mark.qt_serial
def test_replay_shortcut_invokes_replay_without_using_the_mouse(tmp_path, qtbot) -> None:
    sentence = "They listen today."
    answer = "listen"
    question = ContentQuestion(
        id="q-replay-shortcut",
        sentence_id="s-replay-shortcut",
        sentence_text=sentence,
        category="daily",
        source_url="https://example.test/replay-shortcut",
        normalized_hash="replay-shortcut-hash",
        difficulty="easy",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=1,
        difficulty_score=1.0,
        rationale="重听快捷键测试",
        aliases=(),
    )

    class SingleQuestionRepository:
        def list_questions(self, **_filters):
            return [question]

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            SingleQuestionRepository(),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "easy", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    QCoreApplication.processEvents()

    replay_shortcut = root.findChild(QObject, "replayShortcut")
    assert replay_shortcut is not None
    assert str(replay_shortcut.property("sequence")) == "Ctrl+R"

    QMetaObject.invokeMethod(replay_shortcut, "activated")
    QCoreApplication.processEvents()

    assert controller.replayCount == 1


@pytest.mark.qt_serial
def test_correct_answer_reveals_the_full_sentence_translation(tmp_path, qtbot) -> None:
    sentence = "They listen today."
    answer = "listen"
    question = ContentQuestion(
        id="q-correct-translation",
        sentence_id="s-correct-translation",
        sentence_text=sentence,
        category="daily",
        source_url="https://example.test/correct-translation",
        normalized_hash="correct-translation-hash",
        difficulty="easy",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=1,
        difficulty_score=1.0,
        rationale="正确答案翻译测试",
        aliases=(),
        translation_zh="他们今天听了。",
    )

    class SingleQuestionRepository:
        def list_questions(self, **_filters):
            return [question]

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            SingleQuestionRepository(),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "easy", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    QCoreApplication.processEvents()

    translation_panel = root.findChild(QQuickItem, "translationPanel")
    assert translation_panel is not None
    assert translation_panel.property("visible") is False

    controller.submitAnswers(["listen"])
    QCoreApplication.processEvents()

    assert translation_panel.property("visible") is True
