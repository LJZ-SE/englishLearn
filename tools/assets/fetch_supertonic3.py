from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class AssetFile:
    path: str
    sha256: str | None


@dataclass(frozen=True, slots=True)
class AssetManifest:
    repository: str
    revision: str
    files: tuple[AssetFile, ...]


def load_asset_manifest(path: str | Path) -> AssetManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    revision = str(payload.get("revision", ""))
    if _COMMIT_PATTERN.fullmatch(revision) is None:
        raise ValueError("Supertonic revision 必须是完整的提交 SHA")

    repository = str(payload.get("repository", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Hugging Face 仓库名称无效")

    files: list[AssetFile] = []
    seen: set[str] = set()
    for raw_file in payload.get("files", []):
        asset_path = str(raw_file.get("path", ""))
        posix_path = PurePosixPath(asset_path)
        if not asset_path or posix_path.is_absolute() or ".." in posix_path.parts:
            raise ValueError(f"资产路径不安全：{asset_path}")
        if asset_path in seen:
            raise ValueError(f"资产路径重复：{asset_path}")
        seen.add(asset_path)

        expected_hash = raw_file.get("sha256")
        if expected_hash is not None:
            expected_hash = str(expected_hash)
            if _SHA256_PATTERN.fullmatch(expected_hash) is None:
                raise ValueError(f"SHA-256 格式无效：{asset_path}")
        files.append(AssetFile(asset_path, expected_hash))

    if not files:
        raise ValueError("资产清单不能为空")
    return AssetManifest(repository, revision, tuple(files))


def model_url(manifest: AssetManifest, asset_path: str) -> str:
    repository = quote(manifest.repository, safe="/")
    path = quote(asset_path, safe="/")
    return f"https://huggingface.co/{repository}/resolve/{manifest.revision}/{path}?download=true"


def _download_asset_once(url: str, target: Path, expected_sha256: str | None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ListeningClozeBuilder/1"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
    if target.stat().st_size == 0:
        raise ValueError(f"下载到了空资产：{target.name}")
    if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
        raise ValueError(
            f"资产 SHA-256 校验失败：{target.name}，"
            f"期望 {expected_sha256}，实际 {digest.hexdigest()}"
        )


def _download_asset(url: str, target: Path, expected_sha256: str | None) -> None:
    for attempt in range(1, 4):
        try:
            _download_asset_once(url, target, expected_sha256)
            return
        except (OSError, ValueError):
            target.unlink(missing_ok=True)
            if attempt == 3:
                raise
            # 大模型下载偶尔会被中间网络设备中断，退避后从头校验更可靠。
            time.sleep(2**attempt)


def fetch_assets(manifest: AssetManifest, destination: str | Path) -> None:
    destination_path = Path(destination).resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination_path.name}-", dir=destination_path.parent
    ) as temporary_directory:
        staged = Path(temporary_directory) / destination_path.name
        for index, asset in enumerate(manifest.files, start=1):
            print(f"[{index}/{len(manifest.files)}] 下载 {asset.path}", flush=True)
            _download_asset(model_url(manifest, asset.path), staged / asset.path, asset.sha256)

        runtime_manifest = {
            "repository": manifest.repository,
            "revision": manifest.revision,
            "files": [{"path": asset.path, "sha256": asset.sha256} for asset in manifest.files],
        }
        (staged / "asset-manifest.json").write_text(
            json.dumps(runtime_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # 只在所有下载与哈希校验通过后替换目标，避免留下半套模型。
        backup = destination_path.with_name(f".{destination_path.name}.previous")
        if backup.exists():
            shutil.rmtree(backup)
        if destination_path.exists():
            destination_path.rename(backup)
        try:
            staged.rename(destination_path)
        except BaseException:
            if backup.exists() and not destination_path.exists():
                backup.rename(destination_path)
            raise
        if backup.exists():
            shutil.rmtree(backup)


def main() -> int:
    parser = argparse.ArgumentParser(description="下载并校验固定版本的 Supertonic 3 资产")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("supertonic3_assets.json"),
    )
    parser.add_argument("--destination", type=Path, required=True)
    arguments = parser.parse_args()
    fetch_assets(load_asset_manifest(arguments.manifest), arguments.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
