from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtQml import QQmlApplicationEngine

from listening_cloze.application.asset_health import check_bundled_assets
from listening_cloze.application.controller import PracticeController
from listening_cloze.application.dictionary_interactions import (
    DictionaryInteractionService,
)
from listening_cloze.application.dictionary_models import DictionaryViewModel
from listening_cloze.application.learning_models import LearningCenterViewModel
from listening_cloze.application.learning_service import LearningCenterService
from listening_cloze.application.practice_engine import PracticeEngine
from listening_cloze.application.vocabulary_dictation import (
    VocabularyDictationService,
)
from listening_cloze.infrastructure.audio_cache import AudioCache, AudioProfile
from listening_cloze.infrastructure.database import ContentRepository, UserRepository
from listening_cloze.infrastructure.dictionary import DictionaryRepository
from listening_cloze.infrastructure.paths import AppPaths, get_app_paths
from listening_cloze.infrastructure.supertonic_backend import SupertonicBackend
from listening_cloze.infrastructure.tts_service import TtsPrefetchService
from listening_cloze.runtime import data_path, ui_path


@dataclass(frozen=True, slots=True)
class ControllerResources:
    paths: AppPaths
    content_path: Path
    model_path: Path
    learning_center: LearningCenterViewModel
    dictionary_path: Path
    dictionary: DictionaryViewModel


def create_default_controller(
    *,
    user_data_root: str | Path | None = None,
    content_database: str | Path | None = None,
    model_directory: str | Path | None = None,
    dictionary_database: str | Path | None = None,
) -> PracticeController:
    controller, resources = create_runtime_controller(
        user_data_root=user_data_root,
        content_database=content_database,
        model_directory=model_directory,
        dictionary_database=dictionary_database,
    )
    activate_runtime_resources(
        controller,
        resources,
        check_runtime_resources(resources),
    )
    return controller


def create_runtime_controller(
    *,
    user_data_root: str | Path | None = None,
    content_database: str | Path | None = None,
    model_directory: str | Path | None = None,
    dictionary_database: str | Path | None = None,
) -> tuple[PracticeController, ControllerResources]:
    paths = get_app_paths(root=user_data_root)
    paths.ensure_directories()
    content_path = (
        Path(content_database) if content_database is not None else data_path("content.db")
    )
    model_path = Path(model_directory) if model_directory is not None else data_path("supertonic-3")
    dictionary_path = (
        Path(dictionary_database)
        if dictionary_database is not None
        else data_path("ecdict/dictionary.db")
    )
    content_repository = ContentRepository(content_path)
    user_repository = UserRepository(paths.user_db, backups_dir=paths.backups)
    engine = PracticeEngine(
        content_repository,
        user_repository,
    )
    dictionary_repository = DictionaryRepository(dictionary_path)
    controller = PracticeController(
        engine,
        vocabulary_dictation=VocabularyDictationService(
            user_repository,
            dictionary_repository,
        ),
    )
    learning_center = LearningCenterViewModel(
        LearningCenterService(content_repository, user_repository)
    )
    dictionary = DictionaryViewModel(
        dictionary_repository,
        interactions=DictionaryInteractionService(user_repository),
    )
    return controller, ControllerResources(
        paths,
        content_path,
        model_path,
        learning_center,
        dictionary_path,
        dictionary,
    )


def check_runtime_resources(resources: ControllerResources) -> list[str]:
    return check_bundled_assets(
        resources.content_path,
        resources.model_path,
        resources.dictionary_path,
    )


def activate_runtime_resources(
    controller: PracticeController,
    resources: ControllerResources,
    issues: list[str],
) -> None:
    if issues:
        controller.setStartupIssues(issues)
        return
    if controller.repairIssues:
        return

    voice_path = resources.model_path / "voice_styles" / "F3.json"
    voice_hash = hashlib.sha256(voice_path.read_bytes()).hexdigest()
    profile = replace(AudioProfile.default(), voice_sha256=voice_hash)
    tts_service = TtsPrefetchService(
        SupertonicBackend(
            resources.model_path,
            voice=profile.voice,
            steps=profile.steps,
            synthesis_speed=profile.synthesis_speed,
            target_rms_dbfs=profile.target_rms_dbfs,
            peak_ceiling_dbfs=profile.peak_ceiling_dbfs,
        ),
        AudioCache(resources.paths.audio_cache),
        profile,
        on_ready=controller.handleTtsReady,
        on_error=controller.handleTtsError,
    )
    controller.attachTts(tts_service)
    resources.dictionary.attachTts(tts_service)


def load_qml_engine(
    controller: PracticeController,
    learning_center: LearningCenterViewModel | None = None,
    dictionary: DictionaryViewModel | None = None,
) -> QQmlApplicationEngine:
    engine = QQmlApplicationEngine()
    engine.setInitialProperties(
        {
            "backend": controller,
            "learning": learning_center,
            "dictionary": dictionary,
        }
    )
    engine.load(ui_path("Main.qml"))
    if not engine.rootObjects():
        raise RuntimeError("主界面 QML 加载失败")
    return engine
