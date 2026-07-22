from __future__ import annotations

import html
import re
import tempfile
import xml.etree.ElementTree as element_tree
from collections.abc import Iterator
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import py7zr

from tools.content_pipeline.archive_safety import validate_archive_member_path
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import scene_by_key

_SUPPORTED_SITES = frozenset(
    {"workplace", "academia", "softwareengineering", "fitness"}
)
_TARGET_MEMBERS = frozenset({"Posts.xml", "Users.xml"})
_MAX_TARGET_MEMBER_BYTES = 3 * 1024 * 1024 * 1024
_MAX_TOTAL_TARGET_BYTES = 4 * 1024 * 1024 * 1024
_LICENSE_HELP_URL = "https://stackoverflow.com/help/licensing"
_ANGLE_TAG_PATTERN = re.compile(r"<([^<>]+)>")
_TAG_TOKEN = re.compile(r"[a-z0-9.+#-]{1,35}")
_SPACE = re.compile(r"\s+")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_LEXICAL_WORD = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)?")
_MIN_WORDS = 4
_MAX_WORDS = 48
_LICENSE_PATTERN = re.compile(r"cc\s+by-sa\s+(2[.]5|3[.]0|4[.]0)")
_CREATION_DATE_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:[.]\d{1,6})?(?:Z|[+]00:00)?"
)

# 仅使用站点内语义明确的标签，避免把一个帖子误投到多个训练场景。
_SITE_TAG_SCENES: dict[str, dict[str, str]] = {
    "workplace": {
        "job-search": "work_jobs",
        "interviewing": "work_jobs",
        "career-development": "work_jobs",
        "resumes": "work_jobs",
        "workplace-politics": "work_office",
        "office": "work_office",
        "management": "work_office",
        "coworkers": "work_office",
    },
    "academia": {
        "exams": "study_exams",
        "oral-exams": "study_exams",
        "qualifying-exams": "study_exams",
        "admissions": "study_campus",
        "graduate-school": "study_campus",
        "undergraduate": "study_campus",
        "research": "study_academic",
        "literature-review": "study_academic",
        "publications": "study_academic",
        "peer-review": "study_academic",
        "phd": "study_academic",
    },
    "softwareengineering": {
        "design": "technology_software",
        "testing": "technology_software",
        "architecture": "technology_software",
        "code-review": "technology_software",
        "agile": "technology_software",
        "requirements": "technology_software",
    },
    "fitness": {
        "strength-training": "health_fitness",
        "cardio": "health_fitness",
        "running": "health_fitness",
        "weight-loss": "health_fitness",
        "exercise": "health_fitness",
        "protein": "health_fitness",
        "nutrition": "health_fitness",
    },
}

# 同时命中多个强标签时保持确定性；不会将同一个帖子复制到多个场景。
_SCENE_PRIORITY = {
    "work_jobs": 0,
    "work_office": 1,
    "study_exams": 0,
    "study_campus": 1,
    "study_academic": 2,
    "technology_software": 0,
    "health_fitness": 0,
}


class _VisibleTextParser(HTMLParser):
    """只收集段落正文，彻底丢弃非自然语言和链接容器。"""

    _BLOCKED = frozenset({"code", "pre", "blockquote", "script", "style", "ul", "ol", "li", "a"})
    _BREAKS = frozenset({"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = tag.casefold()
        if normalized in self._BLOCKED:
            self._blocked_depth += 1
        elif self._blocked_depth == 0 and normalized in self._BREAKS:
            self._parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self._blocked_depth == 0 and tag.casefold() in self._BREAKS:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in self._BLOCKED and self._blocked_depth:
            self._blocked_depth -= 1
        elif self._blocked_depth == 0 and normalized in self._BREAKS:
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._blocked_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return _SPACE.sub(" ", "".join(self._parts)).strip()


def iter_stackexchange_sentences(
    archive_path: Path, *, site: str
) -> Iterator[CollectedSentence]:
    """解析官方 Stack Exchange 7z dump 中标签归属明确的提问正文。"""
    normalized_site = site.casefold().strip()
    if normalized_site not in _SUPPORTED_SITES:
        raise ValueError(f"Stack Exchange site 不受支持: {site}")

    with tempfile.TemporaryDirectory(prefix="stackexchange-dump-") as temporary_directory:
        target_directory = Path(temporary_directory)
        _extract_target_members(archive_path, target_directory)
        authors = _read_users(target_directory / "Users.xml")
        emitted_ids: set[str] = set()
        emitted = 0
        for post in _iter_question_posts(target_directory / "Posts.xml"):
            sub_scene = _scene_for_tags(normalized_site, post.tags)
            if sub_scene is None:
                continue
            author = authors.get(post.owner_user_id, "") or post.owner_display_name
            scene = scene_by_key(sub_scene)
            for sentence_index, text in enumerate(_body_sentences(post.body), start=1):
                stable_id = (
                    f"stackexchange:{normalized_site}:post:{post.post_id}:"
                    f"sentence:{sentence_index}"
                )
                if stable_id in emitted_ids:
                    raise ValueError(f"Stack Exchange 存在重复稳定 ID: {stable_id}")
                emitted_ids.add(stable_id)
                emitted += 1
                yield CollectedSentence(
                    text=text,
                    source_item_id=stable_id,
                    source_author=author,
                    source_url=(
                        f"https://{normalized_site}.stackexchange.com/questions/"
                        f"{post.post_id}"
                    ),
                    source_name=f"stackexchange-{normalized_site}-official-dump",
                    license_name=post.content_license,
                    license_url=_LICENSE_HELP_URL,
                    top_scene=scene.top_key,
                    sub_scene=scene.key,
                )
        if emitted == 0:
            raise ValueError(f"Stack Exchange dump 没有可映射的自然句: {archive_path}")


class _QuestionPost:
    __slots__ = (
        "post_id",
        "owner_user_id",
        "owner_display_name",
        "creation_date",
        "content_license",
        "tags",
        "body",
    )

    def __init__(
        self,
        *,
        post_id: str,
        owner_user_id: str,
        owner_display_name: str,
        creation_date: str,
        content_license: str,
        tags: tuple[str, ...],
        body: str,
    ) -> None:
        self.post_id = post_id
        self.owner_user_id = owner_user_id
        self.owner_display_name = owner_display_name
        self.creation_date = creation_date
        self.content_license = content_license
        self.tags = tags
        self.body = body


def _extract_target_members(archive_path: Path, target_directory: Path) -> None:
    try:
        with py7zr.SevenZipFile(
            archive_path,
            mode="r",
            max_extract_size=_MAX_TOTAL_TARGET_BYTES,
        ) as archive:
            target_members = _validated_target_members(archive)
            archive.extract(path=target_directory, targets=target_members)
    except (
        OSError,
        py7zr.Bad7zFile,
        py7zr.PasswordRequired,
        py7zr.exceptions.CrcError,
        py7zr.exceptions.UnsupportedCompressionMethodError,
        py7zr.exceptions.InternalError,
        py7zr.DecompressionBombError,
        py7zr.DecompressionError,
    ) as error:
        raise ValueError(f"Stack Exchange 下载内容不是有效 7z: {archive_path}") from error

    for member in _TARGET_MEMBERS:
        path = target_directory / member
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Stack Exchange 安全提取失败: {member}")


def _validated_target_members(archive: py7zr.SevenZipFile) -> list[str]:
    seen_names: set[str] = set()
    seen_target_basenames: set[str] = set()
    target_members: dict[str, int] = {}
    for info in archive.list():
        name = str(info.filename)
        validate_archive_member_path(name, label="Stack Exchange")
        if name in seen_names:
            raise ValueError(f"Stack Exchange 存在重复归档成员: {name}")
        seen_names.add(name)
        if Path(name).name in _TARGET_MEMBERS:
            target_basename = Path(name).name
            if target_basename in seen_target_basenames or name != target_basename:
                raise ValueError(f"Stack Exchange 存在重复或漂移目标成员: {name}")
            seen_target_basenames.add(target_basename)
        if info.is_symlink:
            raise ValueError(f"Stack Exchange 成员不能是链接: {name}")
        if not info.is_file and not info.is_directory:
            raise ValueError(f"Stack Exchange 成员不是普通文件: {name}")
        if name in _TARGET_MEMBERS:
            if not info.is_file:
                raise ValueError(f"Stack Exchange 目标成员不是普通文件: {name}")
            size = int(info.uncompressed)
            if size < 0 or size > _MAX_TARGET_MEMBER_BYTES:
                raise ValueError(f"Stack Exchange 目标成员解压超额: {name}")
            target_members[name] = size
    if set(target_members) != _TARGET_MEMBERS:
        raise ValueError("Stack Exchange dump 结构漂移: 必须恰好包含 Posts.xml 与 Users.xml")
    if sum(target_members.values()) > _MAX_TOTAL_TARGET_BYTES:
        raise ValueError("Stack Exchange 目标成员合计解压超额")
    return sorted(target_members)


def _read_users(path: Path) -> dict[str, str]:
    authors: dict[str, str] = {}
    for row in _iter_rows(path, expected_root="users", label="Users.xml"):
        user_id = _validated_id(
            _required_attribute(row, "Id", "Users.xml row"),
            label="Users.xml row Id",
            allow_community=True,
        )
        display_name = _optional_attribute(row, "DisplayName")
        if user_id in authors:
            raise ValueError(f"Users.xml 存在重复 Id: {user_id}")
        authors[user_id] = display_name
    return authors


def _iter_question_posts(path: Path) -> Iterator[_QuestionPost]:
    seen_post_ids: set[str] = set()
    for row in _iter_rows(path, expected_root="posts", label="Posts.xml"):
        post_type = _required_attribute(row, "PostTypeId", "Posts.xml row")
        if post_type != "1":
            continue
        post_id = _validated_id(
            _required_attribute(row, "Id", "Posts.xml question"),
            label="Posts.xml question Id",
        )
        if post_id in seen_post_ids:
            raise ValueError(f"Posts.xml 存在重复 Id: {post_id}")
        seen_post_ids.add(post_id)
        body = _required_attribute(row, "Body", "Posts.xml question")
        tags = _parse_tags(_required_attribute(row, "Tags", "Posts.xml question"))
        creation_date = _required_attribute(row, "CreationDate", "Posts.xml question")
        _validate_creation_date(creation_date)
        owner_user_id = _optional_attribute(row, "OwnerUserId")
        if owner_user_id:
            owner_user_id = _validated_id(
                owner_user_id,
                label="Posts.xml question OwnerUserId",
                allow_community=True,
            )
        yield _QuestionPost(
            post_id=post_id,
            owner_user_id=owner_user_id,
            owner_display_name=_optional_attribute(row, "OwnerDisplayName"),
            creation_date=creation_date,
            content_license=_normalize_license(
                _required_attribute(row, "ContentLicense", "Posts.xml question")
            ),
            tags=tags,
            body=body,
        )


def _iter_rows(
    path: Path, *, expected_root: str, label: str
) -> Iterator[element_tree.Element]:
    try:
        context = element_tree.iterparse(path, events=("start", "end"))
        depth = 0
        root_seen = False
        for event, element in context:
            if event == "start":
                depth += 1
                if depth == 1:
                    if element.tag != expected_root:
                        raise ValueError(f"{label} 根节点结构漂移")
                    root_seen = True
                elif depth != 2 or element.tag != "row":
                    raise ValueError(f"{label} 子节点结构漂移")
                continue
            if depth == 2:
                yield element
                element.clear()
            depth -= 1
        if not root_seen or depth != 0:
            raise ValueError(f"{label} 根节点结构漂移")
    except (element_tree.ParseError, UnicodeDecodeError) as error:
        raise ValueError(f"{label} 不是有效 XML") from error


def _parse_tags(value: str) -> tuple[str, ...]:
    normalized = value.casefold().strip()
    if normalized.startswith("|") or normalized.endswith("|"):
        parts = normalized.split("|")
        if len(parts) < 3 or parts[0] or parts[-1]:
            raise ValueError("Posts.xml question Tags 结构漂移")
        tags = tuple(parts[1:-1])
    else:
        tags = tuple(_ANGLE_TAG_PATTERN.findall(normalized))
        if "".join(f"<{tag}>" for tag in tags) != normalized:
            raise ValueError("Posts.xml question Tags 结构漂移")
    if (
        not tags
        or len(set(tags)) != len(tags)
        or any(_TAG_TOKEN.fullmatch(tag) is None for tag in tags)
    ):
        raise ValueError("Posts.xml question Tags 结构漂移")
    return tags


def _scene_for_tags(site: str, tags: tuple[str, ...]) -> str | None:
    scenes = _SITE_TAG_SCENES[site]
    candidates = {scenes[tag] for tag in tags if tag in scenes}
    if not candidates:
        return None
    return min(candidates, key=lambda scene: _SCENE_PRIORITY[scene])


def _body_sentences(body: str) -> Iterator[str]:
    parser = _VisibleTextParser()
    parser.feed(html.unescape(body))
    parser.close()
    for raw_sentence in _SENTENCE_BOUNDARY.split(parser.text()):
        sentence = _SPACE.sub(" ", raw_sentence).strip()
        if not sentence or sentence[-1] not in ".?!":
            continue
        if not _MIN_WORDS <= len(_LEXICAL_WORD.findall(sentence)) <= _MAX_WORDS:
            continue
        if "http://" in sentence.casefold() or "https://" in sentence.casefold():
            continue
        yield sentence


def _validate_creation_date(creation_date: str) -> None:
    if _CREATION_DATE_PATTERN.fullmatch(creation_date) is None:
        raise ValueError("Posts.xml question CreationDate 必须是官方完整 datetime")
    try:
        parsed = datetime.fromisoformat(creation_date.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Posts.xml question CreationDate 必须是有效 ISO 时间") from None
    if parsed.tzinfo is not None and parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("Posts.xml question CreationDate 时区必须为 UTC 或 naive")


def _validated_id(value: str, *, label: str, allow_community: bool = False) -> str:
    if allow_community and value == "-1":
        return value
    if not value.isascii() or not value.isdigit() or int(value) <= 0:
        raise ValueError(f"{label} 必须是正整数")
    return value


def _normalize_license(value: str) -> str:
    normalized = _SPACE.sub(" ", value).casefold()
    match = _LICENSE_PATTERN.fullmatch(normalized)
    if match is None:
        raise ValueError("Posts.xml question ContentLicense 不受支持")
    return f"CC BY-SA {match.group(1)}"


def _required_attribute(element: element_tree.Element, name: str, label: str) -> str:
    value = _optional_attribute(element, name)
    if not value:
        raise ValueError(f"{label} 缺少 {name}")
    return value


def _optional_attribute(element: element_tree.Element, name: str) -> str:
    value = element.attrib.get(name)
    return value.strip() if isinstance(value, str) else ""
