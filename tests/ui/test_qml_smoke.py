import pytest
from PySide6.QtCore import QObject
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

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
        "answerFields",
        "submitButton",
        "mascot",
        "progressTrack",
        "repairPage",
        "resumeButton",
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
