from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from PySide6.QtQml import QQmlApplicationEngine

from listening_cloze.application.asset_health import check_bundled_assets
from listening_cloze.application.controller import PracticeController
from listening_cloze.application.practice_engine import PracticeEngine
from listening_cloze.infrastructure.audio_cache import AudioCache, AudioProfile
from listening_cloze.infrastructure.database import ContentRepository, UserRepository
from listening_cloze.infrastructure.paths import get_app_paths
from listening_cloze.infrastructure.supertonic_backend import SupertonicBackend
from listening_cloze.infrastructure.tts_service import TtsPrefetchService
from listening_cloze.runtime import data_path, ui_path


def create_default_controller(
    *,
    user_data_root: str | Path | None = None,
    content_database: str | Path | None = None,
    model_directory: str | Path | None = None,
) -> PracticeController:
    paths = get_app_paths(root=user_data_root)
    paths.ensure_directories()
    content_path = (
        Path(content_database) if content_database is not None else data_path("content.db")
    )
    model_path = Path(model_directory) if model_directory is not None else data_path("supertonic-3")
    engine = PracticeEngine(
        ContentRepository(content_path),
        UserRepository(paths.user_db, backups_dir=paths.backups),
    )
    controller = PracticeController(engine)
    issues = check_bundled_assets(content_path, model_path)
    if issues:
        controller.setStartupIssues(issues)
        return controller

    voice_path = model_path / "voice_styles" / "F3.json"
    voice_hash = hashlib.sha256(voice_path.read_bytes()).hexdigest()
    profile = replace(AudioProfile.default(), voice_sha256=voice_hash)
    tts_service = TtsPrefetchService(
        SupertonicBackend(
            model_path,
            voice=profile.voice,
            steps=profile.steps,
            synthesis_speed=profile.synthesis_speed,
        ),
        AudioCache(paths.audio_cache),
        profile,
        on_ready=controller.handleTtsReady,
        on_error=controller.handleTtsError,
    )
    controller.attachTts(tts_service)
    return controller


def load_qml_engine(controller: PracticeController) -> QQmlApplicationEngine:
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    if not engine.rootObjects():
        raise RuntimeError("主界面 QML 加载失败")
    return engine
