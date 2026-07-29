from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication

from listening_cloze.runtime import ui_path


@pytest.mark.qt_serial
@pytest.mark.parametrize(
    "filename",
    (
        "VocabularyMasteryDots.qml",
        "VocabularyDictionaryFeedbackCard.qml",
        "VocabularyDictationConfigPage.qml",
        "VocabularyDictationPage.qml",
        "VocabularyDictationSummaryPage.qml",
    ),
)
def test_vocabulary_dictation_components_load_independently(filename: str) -> None:
    application = QApplication.instance() or QApplication([])
    assert application is not None
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(ui_path(filename))))

    item = component.create()

    assert item is not None, [error.toString() for error in component.errors()]
    QCoreApplication.processEvents()
    item.deleteLater()


def test_vocabulary_dictation_pages_only_use_the_approved_controller_contract() -> None:
    sources = {
        filename: ui_path(filename).read_text(encoding="utf-8")
        for filename in (
            "VocabularyDictationConfigPage.qml",
            "VocabularyDictationPage.qml",
            "VocabularyDictationSummaryPage.qml",
        )
    }
    combined = "\n".join(sources.values())

    assert "vocabularyDictationView" in combined
    for slot in (
        "startVocabularyDictation",
        "resumeVocabularyDictation",
        "submitVocabularyDictationAnswer",
        "requestVocabularyDictationHint",
        "replayVocabularyDictation",
        "nextVocabularyDictationItem",
        "finishVocabularyDictation",
        "exitVocabularyDictation",
    ):
        assert slot in combined
    assert "startVocabularyReview" not in combined


def test_vocabulary_dictation_practice_preserves_phrase_spaces_and_hides_answer_until_needed(
) -> None:
    source = ui_path("VocabularyDictationPage.qml").read_text(encoding="utf-8")

    assert 'objectName: "vocabularyDictationAnswerInput"' in source
    assert "text.trim().length > 0" in source
    assert "Qt.Key_R" in source
    assert 'sequence: "Space"' in source
    assert "!answerInput.activeFocus" in source
    assert 'text: "答案 · " + (page.view.term || "")' in source
    assert "Number(page.view.hintLevel || 0) >= 4" in source
    assert "practiceWaveform" not in source


def test_vocabulary_dictation_qmldir_registers_all_new_components() -> None:
    qmldir = ui_path("qmldir").read_text(encoding="utf-8")

    for component in (
        "VocabularyMasteryDots",
        "VocabularyDictionaryFeedbackCard",
        "VocabularyDictationConfigPage",
        "VocabularyDictationPage",
        "VocabularyDictationSummaryPage",
    ):
        assert component in qmldir
