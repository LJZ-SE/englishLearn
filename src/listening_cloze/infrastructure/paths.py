from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import platformdirs

APP_DIRECTORY_NAME = "ListeningCloze"


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    content_db: Path
    user_db: Path
    audio_cache: Path
    backups: Path
    logs: Path

    def ensure_directories(self) -> None:
        for directory in (self.root, self.audio_cache, self.backups, self.logs):
            directory.mkdir(parents=True, exist_ok=True)


def get_app_paths(
    root: str | Path | None = None,
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> AppPaths:
    if root is None:
        environment = os.environ if environ is None else environ
        override = environment.get("LISTENING_CLOZE_DATA_DIR")
        if override:
            data_root = Path(override)
        else:
            current_platform = platform_name or platform.system()
            if current_platform.casefold() == "windows":
                local_app_data = environment.get("LOCALAPPDATA")
                if not local_app_data:
                    raise RuntimeError("Windows 环境缺少 LOCALAPPDATA，无法确定用户数据目录")
                data_root = Path(local_app_data) / APP_DIRECTORY_NAME
            else:
                data_root = Path(platformdirs.user_data_path(APP_DIRECTORY_NAME, appauthor=False))
    else:
        data_root = Path(root)

    return AppPaths(
        root=data_root,
        content_db=data_root / "content.db",
        user_db=data_root / "user.db",
        audio_cache=data_root / "audio-cache",
        backups=data_root / "backups",
        logs=data_root / "logs",
    )
