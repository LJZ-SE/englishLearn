from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


def prepare_qt_environment() -> None:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    if sys.platform != "darwin" or "QT_QPA_PLATFORM_PLUGIN_PATH" in os.environ:
        return
    source = (
        Path(sys.prefix)
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
        / "PySide6"
        / "Qt"
        / "plugins"
        / "platforms"
    )
    if not source.is_dir():
        return
    target = Path(tempfile.gettempdir()) / f"listening-cloze-qt-platforms-app-{os.getpid()}"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, copy_function=shutil.copy)
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(target)
