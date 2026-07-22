from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    repository_root = Path.cwd()
    if not (repository_root / "tools" / "content_pipeline" / "cli.py").is_file():
        raise RuntimeError("请从 listening-cloze 仓库根目录运行内容管线命令")
    sys.path.insert(0, str(repository_root))
    from tools.content_pipeline.cli import main as pipeline_main

    pipeline_main()
