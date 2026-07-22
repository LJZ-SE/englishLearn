from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    from tools.assets.fetch_supertonic3 import load_asset_manifest
except ModuleNotFoundError:  # 兼容直接按脚本路径执行。
    from fetch_supertonic3 import load_asset_manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_release_metadata(
    *,
    inputs: list[Path],
    output_directory: Path,
    version: str,
    commit: str,
    source_ref: str,
    runner: str,
    model_manifest_path: Path,
    built_at_utc: str | None = None,
) -> tuple[Path, Path]:
    if not inputs:
        raise ValueError("至少需要一个发布文件")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit 必须是完整的 40 位 SHA")

    resolved_inputs = [path.resolve() for path in inputs]
    missing = [str(path) for path in resolved_inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("发布文件不存在：" + "、".join(missing))
    names = [path.name for path in resolved_inputs]
    if len(names) != len(set(names)):
        raise ValueError("发布文件名不能重复")

    model_manifest = load_asset_manifest(model_manifest_path)
    files = [
        {
            "name": path.name,
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
        for path in sorted(resolved_inputs, key=lambda item: item.name.casefold())
    ]
    timestamp = built_at_utc or datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    manifest = {
        "schema_version": 1,
        "product": "ListeningCloze",
        "version": version,
        "built_at_utc": timestamp,
        "source": {"commit": commit, "ref": source_ref},
        "build": {
            "runner": runner,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        },
        "model": {
            "repository": model_manifest.repository,
            "revision": model_manifest.revision,
        },
        "files": files,
    }

    output_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = output_directory / "build-manifest.json"
    sums_path = output_directory / "SHA256SUMS.txt"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sums_path.write_text(
        "".join(f"{item['sha256']}  {item['name']}\n" for item in files),
        encoding="utf-8",
    )
    return manifest_path, sums_path


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Windows 发布包的校验和与构建清单")
    parser.add_argument("--input", type=Path, action="append", required=True, dest="inputs")
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--runner", required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    arguments = parser.parse_args()
    write_release_metadata(
        inputs=arguments.inputs,
        output_directory=arguments.output_directory,
        version=arguments.version,
        commit=arguments.commit,
        source_ref=arguments.source_ref,
        runner=arguments.runner,
        model_manifest_path=arguments.model_manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
