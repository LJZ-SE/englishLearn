from __future__ import annotations

import re
import stat
import zipfile

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:")


def validate_archive_member_path(name: str, *, label: str) -> None:
    """拒绝绝对路径、反斜杠和可造成目录逃逸的路径片段。"""
    if (
        not name
        or name.startswith(("/", "\\"))
        or _WINDOWS_ABSOLUTE.match(name)
        or "\\" in name
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError(f"{label}包含不安全路径: {name}")


def validate_regular_zip_member(info: zipfile.ZipInfo, *, label: str) -> None:
    """ZIP 可伪装 symlink/设备文件；只接受普通文件或无类型位的常规成员。"""
    validate_archive_member_path(info.filename, label=label)
    file_type = stat.S_IFMT((info.external_attr >> 16) & 0xFFFF)
    if info.is_dir() or file_type not in {0, stat.S_IFREG}:
        raise ValueError(f"{label}匹配成员不是普通文件: {info.filename}")
