from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from listening_cloze.qt_environment import prepare_qt_environment  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="截取学习中心标准视口截图")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1536)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument(
        "--page",
        choices=(
            "home",
            "history",
            "wrong-book",
            "vocabulary",
            "dictionary",
            "statistics",
            "settings",
            "summary",
            "repair",
        ),
        default="home",
        help="要截取的学习中心页面",
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
    from listening_cloze.infrastructure.database import ContentRepository, UserRepository
    from listening_cloze.runtime import data_path

    application = QApplication.instance() or QApplication([])
    assert application is not None
    with tempfile.TemporaryDirectory(prefix="listening-cloze-visual-") as data_root:
        content_repository = ContentRepository(data_path("content.db"))
        user_repository = UserRepository(Path(data_root) / "user.db")
        _seed_visual_data(user_repository)
        controller = PracticeController(
            PracticeEngine(
                content_repository,
                user_repository,
            )
        )
        learning_center = LearningCenterViewModel(
            LearningCenterService(content_repository, user_repository)
        )
        controller.setResourceReady()
        engine = load_qml_engine(controller, learning_center)
        window = engine.rootObjects()[0]
        window.setWidth(arguments.width)
        window.setHeight(arguments.height)
        if arguments.page == "settings":
            window.setProperty("learningPage", "settings")
            controller.openSettings()
        elif arguments.page == "summary":
            controller.startQuantitative("daily", "easy", 1)
            controller.revealAnswer()
            controller.nextQuestion()
        elif arguments.page == "repair":
            controller.setStartupIssues(
                [
                    "题库数量异常：应为 30000 个原句 / 90000 道题",
                    "缺少 Supertonic 离线模型资源：onnx/duration_predictor.onnx",
                ]
            )
        else:
            window.setProperty("learningPage", arguments.page)
        learning_center.refresh()
        for _ in range(24):
            QCoreApplication.processEvents()
        QTest.qWait(500)

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


def _seed_visual_data(user_repository) -> None:
    today = date.today()
    user_repository.set_setting("daily_goal", 30)
    for day_offset, completed in enumerate((22, 28, 35, 18, 32, 40, 45)):
        activity_date = today - timedelta(days=6 - day_offset)
        user_repository.record_daily_activity(
            activity_date.isoformat(),
            completed_delta=completed,
            correct_delta=round(completed * 0.79),
            duration_delta=completed * 42,
        )

    sessions = (
        ("visual-cet-4", "cet", "cet_4", 8, 20, 7, False),
        ("visual-travel", "travel", "travel_tourism", 15, 20, 12, True),
        ("visual-news", "news", "news_current", 12, 20, 10, True),
    )
    for session_id, top_scene, sub_scene, completed, target, correct, finished in sessions:
        user_repository.save_session(
            session_id,
            mode="quantitative",
            state={
                "practice_type": "quantitative",
                "top_scene": top_scene,
                "sub_scene": sub_scene,
                "difficulty": "easy",
                "target_count": target,
                "duration_seconds": completed * 42,
                "recorded_duration_seconds": completed * 42,
                "stats": {"completed": completed, "correct": correct},
            },
        )
        if finished:
            user_repository.complete_session(session_id)


if __name__ == "__main__":
    raise SystemExit(main())
