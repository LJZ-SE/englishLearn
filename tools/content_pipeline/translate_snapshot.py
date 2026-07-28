from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


def translate(text: str) -> str:
    query = urlencode(
        {
            "client": "gtx",
            "sl": "en",
            "tl": "zh-CN",
            "dt": "t",
            "q": text,
        }
    )
    endpoint = f"https://translate.googleapis.com/translate_a/single?{query}"
    with urlopen(endpoint, timeout=20) as response:  # noqa: S310
        payload = json.load(response)
    return "".join(part[0] for part in payload[0] if part and part[0]).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="为英文题库快照补充中文翻译")
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--delay", type=float, default=0.08)
    arguments = parser.parse_args()

    items = json.loads(arguments.snapshot.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("题库快照必须是 JSON 数组")

    lock = arguments.snapshot.with_suffix(arguments.snapshot.suffix + ".translate.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError("已有翻译任务正在运行") from error

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(str(os.getpid()))
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise ValueError(f"第 {index} 条题目格式不正确")
            if not str(item.get("translation_zh", "")).strip():
                item["translation_zh"] = translate(item["text"])
                temporary = arguments.snapshot.with_suffix(
                    arguments.snapshot.suffix + f".tmp.{os.getpid()}"
                )
                temporary.write_text(
                    json.dumps(items, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(arguments.snapshot)
                print(f"已翻译 {index}/{len(items)}", flush=True)
                time.sleep(arguments.delay)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
