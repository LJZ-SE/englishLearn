from __future__ import annotations

import argparse
import random
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from listening_cloze.qt_environment import prepare_qt_environment  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="截取答题页标准视口截图")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1536)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument(
        "--long-sentence",
        action="store_true",
        help="使用长句验证首屏内的核心操作是否完整可见",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    prepare_qt_environment()

    from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt
    from PySide6.QtQuick import QQuickItem, QQuickWindow
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from listening_cloze.application.bootstrap import load_qml_engine
    from listening_cloze.application.controller import PracticeController
    from listening_cloze.application.learning_models import LearningCenterViewModel
    from listening_cloze.application.learning_service import LearningCenterService
    from listening_cloze.application.practice_engine import PracticeEngine
    from listening_cloze.infrastructure.database import (
        ContentQuestion,
        UserRepository,
    )

    application = QApplication.instance() or QApplication([])
    assert application is not None
    if arguments.long_sentence:
        sentence = (
            "As a person having my own business, it can fully express myself "
            "and make my own decisions, a privilege not everyone can have, "
            "even those with highly-paid positions."
        )
        answer = "everyone"
        translation = (
            "作为一个拥有自己事业的人，我可以充分表达自己并作出决定，"
            "这是即使身居高薪职位的人也未必拥有的特权。"
        )
    else:
        sentence = "I've always wanted desperately to master an eastern language."
        answer = "wanted desperately"
        translation = "我一直非常想掌握一门东方语言。"
    base_question = ContentQuestion(
        id="visual-practice-1",
        sentence_id="visual-sentence-1",
        sentence_text=sentence,
        category="daily",
        top_scene="daily",
        sub_scene=None,
        source_url="https://example.test/visual-practice",
        normalized_hash="visual-practice-hash-1",
        difficulty="hard" if arguments.long_sentence else "easy",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=len(answer.split()),
        difficulty_score=3.0 if arguments.long_sentence else 1.0,
        rationale="答题页视觉验收",
        aliases=(),
        translation_zh=translation,
    )
    questions = [
        replace(
            base_question,
            id=f"visual-practice-{index + 1}",
            sentence_id=f"visual-sentence-{index + 1}",
            normalized_hash=f"visual-practice-hash-{index + 1}",
        )
        for index in range(10)
    ]

    with tempfile.TemporaryDirectory(prefix="listening-cloze-practice-") as data_root:
        content = _VisualContentRepository(questions)
        users = UserRepository(Path(data_root) / "user.db")
        controller = PracticeController(
            PracticeEngine(
                content,
                users,
            )
        )
        learning_center = LearningCenterViewModel(
            LearningCenterService(content, users)
        )
        controller.setResourceReady()
        controller.startQuantitative(
            "daily",
            "hard" if arguments.long_sentence else "easy",
            10,
        )
        if not arguments.long_sentence:
            for _ in range(3):
                controller.submitAnswers(answer.split())
                controller.nextQuestion()

        engine = load_qml_engine(controller, learning_center)
        window = engine.rootObjects()[0]
        window.setWidth(arguments.width)
        window.setHeight(arguments.height)
        window.show()
        window.requestActivate()
        for _ in range(24):
            QCoreApplication.processEvents()
        first_input = window.findChild(QQuickItem, "answerInput0")
        if first_input is not None:
            first_input.forceActiveFocus()
            first_input.setProperty("focus", True)
            input_origin = first_input.mapToScene(QPointF(0, 0))
            QTest.mouseClick(
                window,
                Qt.LeftButton,
                Qt.NoModifier,
                QPoint(
                    round(input_origin.x() + first_input.width() / 2),
                    round(input_origin.y() + first_input.height() / 2),
                ),
            )
        practice_page = window.findChild(QQuickItem, "practicePage")
        if practice_page is not None:
            practice_page.setProperty("playbackProgress", 1.0)
        QTest.qWait(350)
        if first_input is not None:
            first_input.forceActiveFocus()
            QCoreApplication.processEvents()

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


class _VisualContentRepository:
    def __init__(self, questions) -> None:
        self._questions = list(questions)

    def sample_questions(
        self,
        *,
        top_scene: str | None,
        sub_scene: str | None,
        difficulty: str,
        limit: int,
        exclude_ids: frozenset[str],
        seed: int,
    ):
        candidates = [
            question
            for question in self._questions
            if (top_scene is None or question.top_scene == top_scene)
            and (sub_scene is None or question.sub_scene == sub_scene)
            and question.difficulty == difficulty
            and question.id not in exclude_ids
        ]
        random.Random(seed).shuffle(candidates)
        return candidates[:limit]

    def get_questions_by_ids(self, ids):
        by_id = {question.id: question for question in self._questions}
        return [by_id[question_id] for question_id in ids if question_id in by_id]

    def list_scenes(self):
        from listening_cloze.infrastructure.database import SceneMetadata

        return [SceneMetadata(key="daily", label="日常口语", children=())]


if __name__ == "__main__":
    raise SystemExit(main())
