from __future__ import annotations

import sys
from pathlib import Path


def package_root() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root is not None:
        return Path(bundled_root) / "listening_cloze"
    return Path(__file__).resolve().parent


def ui_path(name: str) -> Path:
    return package_root() / "ui" / "qml" / name


def data_path(name: str) -> Path:
    return package_root() / "data" / name
