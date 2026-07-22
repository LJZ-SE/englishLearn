from __future__ import annotations

import logging
import sys
import tempfile
import wave
from pathlib import Path

from listening_cloze.qt_environment import prepare_qt_environment


def main() -> int:
    prepare_qt_environment()
    smoke_test = "--smoke-test" in sys.argv

    from listening_cloze.infrastructure.logging_config import configure_logging
    from listening_cloze.infrastructure.paths import get_app_paths

    paths = get_app_paths()
    paths.ensure_directories()
    configure_logging(paths.logs)
    try:
        return _run(smoke_test)
    except Exception:
        logging.getLogger("listening_cloze").exception("应用异常退出")
        raise


def _run(smoke_test: bool) -> int:

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    from listening_cloze import APP_NAME, __version__
    from listening_cloze.application.bootstrap import (
        create_default_controller,
        load_qml_engine,
    )

    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(__version__)
    QCoreApplication.setOrganizationName("ListeningCloze")
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    qt_arguments = [argument for argument in sys.argv if argument != "--smoke-test"]
    application = QApplication(qt_arguments)
    controller = create_default_controller()
    engine = load_qml_engine(controller)
    if smoke_test:
        application.processEvents()
        if controller.repairIssues:
            raise RuntimeError("离线资产冒烟检查失败：" + "；".join(controller.repairIssues))
        from listening_cloze.infrastructure.supertonic_backend import SupertonicBackend
        from listening_cloze.runtime import data_path

        smoke_audio = Path(tempfile.gettempdir()) / "listening-cloze-tts-smoke.wav"
        SupertonicBackend(data_path("supertonic-3")).synthesize_to_file(
            "Offline listening practice is ready.",
            smoke_audio,
        )
        with wave.open(str(smoke_audio), "rb") as source:
            if source.getnframes() <= 0 or source.getframerate() != 44_100:
                raise RuntimeError("Supertonic 冒烟检查生成了无效音频")
        smoke_audio.unlink(missing_ok=True)
        controller.shutdown()
        del engine
        return 0
    exit_code = application.exec()
    controller.shutdown()
    del engine
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
