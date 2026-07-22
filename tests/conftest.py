import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

if sys.platform == "darwin":
    source = (
        Path(sys.prefix)
        / "lib"
        / "python3.12"
        / "site-packages"
        / "PySide6"
        / "Qt"
        / "plugins"
        / "platforms"
    )
    target = Path(tempfile.gettempdir()) / f"listening-cloze-qt-platforms-{os.getpid()}"
    if source.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, copy_function=shutil.copy)
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(target))
