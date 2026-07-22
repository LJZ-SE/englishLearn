import random
from pathlib import Path

import pytest

from listening_cloze.application.bootstrap import create_default_controller, load_qml_engine
from listening_cloze.application.controller import PracticeController
from listening_cloze.application.practice_engine import PracticeEngine
from listening_cloze.infrastructure.database import UserRepository


class EmptyContentRepository:
    def list_questions(self, *, category=None, difficulty=None):
        return []


@pytest.mark.qt_serial
def test_qml_engine_receives_the_python_controller(qapp, tmp_path: Path) -> None:
    controller = PracticeController(
        PracticeEngine(
            EmptyContentRepository(),
            UserRepository(tmp_path / "user.db"),
            rng=random.Random(1),
        )
    )

    engine = load_qml_engine(controller)

    assert len(engine.rootObjects()) == 1
    assert engine.rootObjects()[0].property("backend") is controller


def test_default_controller_opens_repair_page_when_offline_assets_are_missing(
    tmp_path: Path,
) -> None:
    controller = create_default_controller(
        user_data_root=tmp_path / "user-data",
        content_database=tmp_path / "missing-content.db",
        model_directory=tmp_path / "missing-supertonic",
    )

    assert controller.currentPage == "repair"
    assert len(controller.repairIssues) == 3
    assert any("哈希清单" in issue for issue in controller.repairIssues)
