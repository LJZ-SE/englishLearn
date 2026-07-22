from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

WORKFLOW = "package-windows.yml"
ARTIFACT = "listening-cloze-windows"


def _require_gh() -> None:
    if shutil.which("gh") is None:
        raise RuntimeError("未找到 GitHub CLI，请先安装 gh 并执行 gh auth login")


def trigger(ref: str) -> None:
    _require_gh()
    subprocess.run(
        ["gh", "workflow", "run", WORKFLOW, "--ref", ref],
        check=True,
    )
    print("Windows 构建已触发。完成后可用 latest 或 download 子命令取回安装包。")


def download(run_id: str, destination: Path) -> None:
    _require_gh()
    subprocess.run(["gh", "run", "watch", run_id, "--exit-status"], check=True)
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gh",
            "run",
            "download",
            run_id,
            "--name",
            ARTIFACT,
            "--dir",
            str(destination),
        ],
        check=True,
    )
    print(f"安装包和校验文件已下载到：{destination.resolve()}")


def latest(ref: str, destination: Path) -> None:
    _require_gh()
    result = subprocess.run(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            WORKFLOW,
            "--branch",
            ref,
            "--limit",
            "1",
            "--json",
            "databaseId",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    runs = json.loads(result.stdout)
    if not runs:
        raise RuntimeError(f"没有找到 ref={ref} 的 Windows 构建")
    download(str(runs[0]["databaseId"]), destination)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在 macOS、Linux 或 Windows 上通过 GitHub CLI 触发并下载 Windows 安装包"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    trigger_parser = commands.add_parser("trigger", help="触发指定分支或标签的 Windows 构建")
    trigger_parser.add_argument("--ref", default="main")

    download_parser = commands.add_parser("download", help="等待指定运行完成并下载产物")
    download_parser.add_argument("--run-id", required=True)
    download_parser.add_argument("--destination", type=Path, default=Path("outputs/windows"))

    latest_parser = commands.add_parser("latest", help="下载指定 ref 最近一次构建")
    latest_parser.add_argument("--ref", default="main")
    latest_parser.add_argument("--destination", type=Path, default=Path("outputs/windows"))

    arguments = parser.parse_args()
    if arguments.command == "trigger":
        trigger(arguments.ref)
    elif arguments.command == "download":
        download(arguments.run_id, arguments.destination)
    else:
        latest(arguments.ref, arguments.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
