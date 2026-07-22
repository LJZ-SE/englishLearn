from __future__ import annotations

import subprocess
import sys


def _run(arguments: list[str]) -> int:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *arguments],
        check=False,
    ).returncode


def main() -> int:
    parallel_result = _run(["-n", "auto", "-m", "not qt_serial"])
    if parallel_result != 0:
        return parallel_result
    return _run(["-m", "qt_serial"])


if __name__ == "__main__":
    raise SystemExit(main())
