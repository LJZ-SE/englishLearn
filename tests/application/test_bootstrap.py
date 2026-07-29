import random
from pathlib import Path

import pytest

from listening_cloze.application.bootstrap import (
    create_default_controller,
    create_runtime_controller,
    load_qml_engine,
)
from listening_cloze.application.controller import PracticeController
from listening_cloze.application.dictionary_models import DictionaryViewModel
from listening_cloze.application.practice_engine import PracticeEngine
from listening_cloze.infrastructure.database import UserRepository
from listening_cloze.infrastructure.dictionary import DictionaryRepository


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

    dictionary = DictionaryViewModel(DictionaryRepository(tmp_path / "dictionary.db"))
    engine = load_qml_engine(controller, dictionary=dictionary)

    assert len(engine.rootObjects()) == 1
    assert engine.rootObjects()[0].property("backend") is controller
    assert engine.rootObjects()[0].property("dictionary") is dictionary


def test_default_controller_opens_repair_page_when_offline_assets_are_missing(
    tmp_path: Path,
) -> None:
    controller = create_default_controller(
        user_data_root=tmp_path / "user-data",
        content_database=tmp_path / "missing-content.db",
        model_directory=tmp_path / "missing-supertonic",
        dictionary_database=tmp_path / "missing-ecdict" / "dictionary.db",
    )

    assert controller.currentPage == "repair"
    assert len(controller.repairIssues) == 5
    assert any("场景目录" in issue for issue in controller.repairIssues)
    assert any("哈希清单" in issue for issue in controller.repairIssues)
    assert any("ECDICT" in issue for issue in controller.repairIssues)


def test_runtime_dictionary_adds_to_the_shared_vocabulary_store(
    tmp_path: Path,
) -> None:
    _controller, resources = create_runtime_controller(
        user_data_root=tmp_path / "user-data",
        content_database=tmp_path / "content.db",
        model_directory=tmp_path / "supertonic",
        dictionary_database=tmp_path / "dictionary.db",
    )

    resources.dictionary.addToVocabulary("kind of")

    entries = UserRepository(resources.paths.user_db).list_vocabulary()
    assert [entry.term for entry in entries] == ["kind of"]
    assert entries[0].source_kind == "dictionary"
