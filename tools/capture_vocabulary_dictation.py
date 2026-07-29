from __future__ import annotations

import argparse
import random
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from listening_cloze.qt_environment import prepare_qt_environment  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="截取词汇听写标准视口截图")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1366)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument(
        "--state",
        choices=("config", "practice", "feedback", "summary"),
        default="practice",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    prepare_qt_environment()

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from listening_cloze.application.bootstrap import load_qml_engine
    from listening_cloze.application.controller import PracticeController
    from listening_cloze.application.learning_models import LearningCenterViewModel
    from listening_cloze.application.learning_service import LearningCenterService
    from listening_cloze.application.practice_engine import PracticeEngine
    from listening_cloze.application.vocabulary_dictation import (
        VocabularyDictationService,
    )
    from listening_cloze.infrastructure.database import (
        ContentRepository,
        UserRepository,
    )
    from listening_cloze.infrastructure.dictionary import DictionaryRepository
    from listening_cloze.runtime import data_path

    application = QApplication.instance() or QApplication([])
    assert application is not None
    with tempfile.TemporaryDirectory(prefix="listening-cloze-vocabulary-") as data_root:
        content = ContentRepository(data_path("content.db"))
        users = UserRepository(Path(data_root) / "user.db")
        for term in ("feature", "immediately", "take part in", "kind of", "street"):
            users.add_dictionary_vocabulary(term=term)
        dictionary = DictionaryRepository(data_path("ecdict/dictionary.db"))
        vocabulary = VocabularyDictationService(
            users,
            dictionary,
            rng=random.Random(9),
        )
        controller = PracticeController(
            PracticeEngine(content, users),
            vocabulary_dictation=vocabulary,
        )
        learning = LearningCenterViewModel(LearningCenterService(content, users))
        controller.setResourceReady()
        engine = load_qml_engine(controller, learning)
        window = engine.rootObjects()[0]
        window.setWidth(arguments.width)
        window.setHeight(arguments.height)

        if arguments.state == "config":
            window.setProperty("learningPage", "vocabulary-dictation-config")
        else:
            controller.startVocabularyDictation("new", 10)
            if arguments.state == "feedback":
                controller.submitVocabularyDictationAnswer("completely wrong")
            elif arguments.state == "summary":
                while controller.currentPage == "vocabulary-dictation":
                    controller.submitVocabularyDictationAnswer("completely wrong")
                    controller.nextVocabularyDictationItem()

        window.show()
        window.requestActivate()
        for _ in range(24):
            QCoreApplication.processEvents()
        QTest.qWait(350)

        image = QQuickWindow.grabWindow(window)
        if image.width() != arguments.width or image.height() != arguments.height:
            image = image.scaled(
                arguments.width,
                arguments.height,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(arguments.output)):
            controller.shutdown()
            raise RuntimeError(f"截图保存失败：{arguments.output}")
        controller.shutdown()
        del engine
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
