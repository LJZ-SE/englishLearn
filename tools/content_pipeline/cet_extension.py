from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import time
import xml.etree.ElementTree as ElementTree
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile

from tools.content_pipeline.candidates import generate_variants
from tools.content_pipeline.clean import clean_sentence, normalized_hash, rejection_reason
from tools.content_pipeline.dedupe import NearDuplicateIndex
from tools.content_pipeline.scenes import SCENES

CET_QUOTA_PER_LEVEL = 3_000
CET_SIMULATED_PER_LEVEL = 150
CET_PAPER_REVISION = "97266755c1d95b13b86ce3e0570390b5f7a89225"
CET_MARKDOWN_REVISION = "ff09688a456e174722d85c1fa150485c93f5e68c"
_LEVELS = ("cet4", "cet6")
_LEVEL_LABELS = {"cet4": "CET-4", "cet6": "CET-6"}
_SUB_SCENES = {"cet4": "cet_cet4", "cet6": "cet_cet6"}
_WORD_XML_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[\"']?[A-Z])")
_OPTION_PREFIX = re.compile(r"^\s*(?:[A-Z]\)|\d{1,3}[.)])\s*")
_PARAGRAPH_PREFIX = re.compile(r"^\s*\[[A-Z]\]\s*")
_MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)]\([^)]*\)")
_MARKDOWN_PREFIX = re.compile(r"^(?:#{1,6}\s*|[-*+>]\s+|\d+[.)]\s*)+")
_TRAILING_CONNECTOR = re.compile(r"\b(?:and|or|the|a|to|of|in)\s*[.!?]$", re.I)
_BOILERPLATE_MARKERS = (
    "directions:",
    "answer sheet",
    "you will hear",
    "marked a)",
    "write at least",
    "no more than",
    "choose the best answer",
    "questions ",
    "you will have 30 minutes",
    "you are to write",
    "after each question",
    "both the conversation",
    "both the conversations",
    "both the news report",
    "both the passage",
    "spoken only once",
    "during the pause",
    "single line through the centre",
    "you may choose a paragraph",
    "each paragraph is marked",
    "when the passage is read",
    "you are required to select",
    "paragraph more than once",
    "are based on the conversation",
)
_BOILERPLATE_PREFIX = re.compile(r"^(?:directions\s*:|questions?\s*\d+)", re.I)
_OCR_BLANK_NUMBER = re.compile(
    r"\b(?:2[6-9]|3\d|4[0-5])\b"
    r"(?!\s*(?:%|percent|years?|minutes?|hours?|days?|weeks?|months?|"
    r"people|students|countries|miles?|kilometers?|km|pounds?|dollars?|"
    r"million|billion))",
    re.I,
)
_OCR_ARTIFACT = re.compile(
    r"(?:[A-Za-z]£|£[A-Za-z]|\bDrechseF(?:'s|s)?\b|\bparents\*\b|"
    r"\bothers\s+1\b|[\"“]1\s+[a-z]|\brand toilet\b|\$\d+\.\s+\d)",
    re.I,
)
_POSITIVE_63_BIT_MASK = (1 << 63) - 1


def create_snapshot(
    *,
    base_database: Path,
    paper_repository: Path,
    markdown_repository: Path,
    cet4_simulated: Path,
    cet6_simulated: Path,
    output: Path,
) -> list[dict[str, str]]:
    translation_cache: dict[str, str] = {}
    if output.is_file():
        for item in _load_snapshot(output):
            translation = item["translation_zh"].strip()
            if translation:
                translation_cache[normalized_hash(item["text"])] = translation

    index = NearDuplicateIndex()
    with sqlite3.connect(base_database) as connection:
        for (text,) in connection.execute("SELECT text FROM sentences ORDER BY id"):
            index.add(str(text))

    selected: dict[str, list[dict[str, str]]] = {level: [] for level in _LEVELS}
    simulated_paths = {"cet4": cet4_simulated, "cet6": cet6_simulated}
    for level in _LEVELS:
        simulated = _load_simulated_items(simulated_paths[level], level)
        for item in simulated:
            text = item["text"]
            _validate_sentence(text)
            if not index.add(text):
                continue
            selected[level].append(
                {
                    "level": level,
                    "origin": "simulated",
                    "text": text,
                    "translation_zh": item["translation_zh"],
                    "source_name": f"{_LEVEL_LABELS[level]} 模拟·项目生成",
                    "source_url": "https://cet.neea.edu.cn/html1/folder/16113/1586-1.htm",
                    "source_author": "",
                    "source_item_id": item["source_item_id"],
                    "license_name": "Project-generated simulation",
                    "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
                }
            )
        if len(selected[level]) != CET_SIMULATED_PER_LEVEL:
            raise ValueError(
                f"{_LEVEL_LABELS[level]} 模拟题去重后应为 "
                f"{CET_SIMULATED_PER_LEVEL} 句，实际为 {len(selected[level])}"
            )

    authentic_candidates = _collect_authentic_candidates(
        paper_repository=paper_repository,
        markdown_repository=markdown_repository,
    )
    for level in _LEVELS:
        target = CET_QUOTA_PER_LEVEL - len(selected[level])
        candidates = sorted(
            authentic_candidates[level],
            key=lambda item: hashlib.sha256(
                f"{level}\0{item['text']}".encode()
            ).hexdigest(),
        )
        accepted = 0
        for item in candidates:
            if accepted >= target:
                break
            if not index.add(item["text"]):
                continue
            selected[level].append(item)
            accepted += 1
        if len(selected[level]) != CET_QUOTA_PER_LEVEL:
            raise ValueError(
                f"{_LEVEL_LABELS[level]} 真题候选不足：需要 {target} 句，"
                f"只选出 {accepted} 句"
            )

    snapshot = [
        item
        for level in _LEVELS
        for item in sorted(
            selected[level],
            key=lambda candidate: (
                candidate["origin"] != "authentic",
                candidate["source_item_id"],
            ),
        )
    ]
    for item in snapshot:
        if not item["translation_zh"]:
            item["translation_zh"] = translation_cache.get(
                normalized_hash(item["text"]), ""
            )
    _write_json_atomically(output, snapshot)
    return snapshot


def translate_snapshot(
    snapshot_path: Path,
    *,
    workers: int = 12,
    checkpoint_size: int = 40,
) -> int:
    payload = _load_snapshot(snapshot_path)
    pending = [
        (index, item["text"])
        for index, item in enumerate(payload)
        if not item["translation_zh"].strip()
    ]
    if not pending:
        return 0

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_translate_with_retry, text): index for index, text in pending
        }
        for future in as_completed(futures):
            index = futures[future]
            payload[index]["translation_zh"] = future.result()
            completed += 1
            if completed % checkpoint_size == 0:
                _write_json_atomically(snapshot_path, payload)
                print(f"已翻译 {completed}/{len(pending)}", flush=True)
    _write_json_atomically(snapshot_path, payload)
    return completed


def publish_extension(
    *,
    base_database: Path,
    snapshot_path: Path,
    database_path: Path,
    report_path: Path,
    sources_path: Path,
) -> None:
    snapshot = _load_snapshot(snapshot_path)
    _validate_snapshot(snapshot)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_database = database_path.with_suffix(database_path.suffix + ".cet.tmp")
    temporary_report = report_path.with_suffix(report_path.suffix + ".cet.tmp")
    temporary_sources = sources_path.with_suffix(sources_path.suffix + ".cet.tmp")
    for path in (temporary_database, temporary_report, temporary_sources):
        path.unlink(missing_ok=True)
    shutil.copy2(base_database, temporary_database)

    try:
        with sqlite3.connect(temporary_database) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            _remove_existing_cet_rows(connection)
            _insert_cet_catalog(connection)
            for item in snapshot:
                _insert_snapshot_item(connection, item)
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("扩展后的 content.db 完整性检查失败")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("扩展后的 content.db 外键检查失败")
            counts = connection.execute(
                """
                SELECT sub_scene_key, COUNT(*)
                FROM sentences
                WHERE sub_scene_key IN ('cet_cet4', 'cet_cet6')
                GROUP BY sub_scene_key
                ORDER BY sub_scene_key
                """
            ).fetchall()
            if counts != [("cet_cet4", 3_000), ("cet_cet6", 3_000)]:
                raise ValueError(f"四六级题量不正确: {counts}")
            report = _build_quality_report(connection)
            sources = _build_source_manifest(connection)

        _write_json_atomically(temporary_report, report)
        _write_json_atomically(temporary_sources, sources)
        temporary_database.replace(database_path)
        temporary_report.replace(report_path)
        temporary_sources.replace(sources_path)
    finally:
        for path in (temporary_database, temporary_report, temporary_sources):
            path.unlink(missing_ok=True)


def _collect_authentic_candidates(
    *,
    paper_repository: Path,
    markdown_repository: Path,
) -> dict[str, list[dict[str, str]]]:
    candidates: dict[str, list[dict[str, str]]] = {level: [] for level in _LEVELS}
    documents = sorted(paper_repository.rglob("*.docx")) + sorted(
        markdown_repository.rglob("cet[46]-*.md")
    )
    for path in documents:
        level = _level_from_path(path)
        if level is None:
            continue
        root = paper_repository if path.suffix.casefold() == ".docx" else markdown_repository
        relative_path = path.relative_to(root).as_posix()
        repository = (
            "DieDiDi/CET4-6-past-exam-paper"
            if path.suffix.casefold() == ".docx"
            else "wamich/english-exem-md"
        )
        revision = (
            CET_PAPER_REVISION
            if path.suffix.casefold() == ".docx"
            else CET_MARKDOWN_REVISION
        )
        source_url = (
            f"https://github.com/{repository}/blob/{revision}/{quote(relative_path)}"
        )
        license_name = (
            "Copyrighted exam material; private study only"
            if path.suffix.casefold() == ".docx"
            else "GPL-2.0"
        )
        license_url = (
            f"https://github.com/{repository}"
            if path.suffix.casefold() == ".docx"
            else f"https://github.com/{repository}/blob/{revision}/LICENSE"
        )
        session = _exam_session(relative_path)
        paragraphs = (
            _iter_docx_paragraphs(path)
            if path.suffix.casefold() == ".docx"
            else _iter_markdown_paragraphs(path)
        )
        for paragraph_index, paragraph in enumerate(paragraphs, start=1):
            for sentence_index, text in enumerate(_split_sentences(paragraph), start=1):
                if not _is_authentic_candidate(text):
                    continue
                candidates[level].append(
                    {
                        "level": level,
                        "origin": "authentic",
                        "text": text,
                        "translation_zh": "",
                        "source_name": f"{_LEVEL_LABELS[level]} 真题·{session}",
                        "source_url": source_url,
                        "source_author": "",
                        "source_item_id": (
                            f"authentic:{level}:{revision[:10]}:{relative_path}:"
                            f"p{paragraph_index:04d}:s{sentence_index:02d}"
                        ),
                        "license_name": license_name,
                        "license_url": license_url,
                    }
                )
    return candidates


def _iter_docx_paragraphs(path: Path):
    with ZipFile(path) as archive:
        document = archive.read("word/document.xml")
    root = ElementTree.fromstring(document)
    for paragraph in root.iter(f"{_WORD_XML_NAMESPACE}p"):
        text = "".join(
            node.text or "" for node in paragraph.iter(f"{_WORD_XML_NAMESPACE}t")
        ).strip()
        if text:
            yield text


def _iter_markdown_paragraphs(path: Path):
    text = path.read_text(encoding="utf-8")
    text = _MARKDOWN_LINK.sub(lambda match: match.group(1), text)
    text = re.sub(r"<[^>]+>", " ", text)
    for block in re.split(r"\n\s*\n", text):
        cleaned = _MARKDOWN_PREFIX.sub("", block.strip())
        if cleaned:
            yield cleaned


def _split_sentences(paragraph: str) -> list[str]:
    normalized = clean_sentence(paragraph)
    normalized = re.sub(r"(?<=\d)\s*,\s*(?=\d{3}\b)", ",", normalized)
    normalized = re.sub(r"(?<=\d)\.\s+(?=\d\b)", ".", normalized)
    return [
        _PARAGRAPH_PREFIX.sub("", _OPTION_PREFIX.sub("", clean_sentence(part)))
        for part in _SENTENCE_BOUNDARY.split(normalized)
        if clean_sentence(part)
    ]


def _is_authentic_candidate(text: str) -> bool:
    lowered = text.casefold()
    if any(marker in lowered for marker in _BOILERPLATE_MARKERS):
        return False
    if _BOILERPLATE_PREFIX.search(text):
        return False
    if _TRAILING_CONNECTOR.search(text) or rejection_reason(text) is not None:
        return False
    if (
        "_" in text
        or "____" in text
        or re.search(r"\(\s*\d+\s*\)", text)
        or re.search(r"[\u4e00-\u9fff]", text)
        or re.search(r"&\s*\d", text)
        or _OCR_BLANK_NUMBER.search(text)
        or _OCR_ARTIFACT.search(text)
        or text.startswith("S. is ")
    ):
        return False
    try:
        generate_variants(text)
    except ValueError:
        return False
    return True


def _load_simulated_items(path: Path, level: str) -> list[dict[str, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"模拟题文件必须是 JSON 数组: {path}")
    items: list[dict[str, str]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path} 第 {index} 项不是对象")
        normalized = {
            "text": str(item.get("text", "")).strip(),
            "translation_zh": str(item.get("translation_zh", "")).strip(),
            "source_item_id": str(item.get("source_item_id", "")).strip(),
        }
        if (
            not normalized["translation_zh"]
            or not normalized["source_item_id"].startswith(f"simulated:{level}:")
        ):
            raise ValueError(f"{path} 第 {index} 项缺少翻译或 ID 不符合级别")
        items.append(normalized)
    return items


def _level_from_path(path: Path) -> str | None:
    name = path.name.casefold()
    if "cet4" in name or "四级" in name:
        return "cet4"
    if "cet6" in name or "六级" in name:
        return "cet6"
    return None


def _exam_session(path: str) -> str:
    match = re.search(r"(20\d{2})[年._-]?\s*(1[0-2]|0?[1-9])月?", path)
    return f"{match.group(1)}-{int(match.group(2)):02d}" if match else "历年试卷"


def _validate_sentence(text: str) -> None:
    reason = rejection_reason(text)
    if reason is not None:
        raise ValueError(f"句子未通过清洗门禁 ({reason}): {text}")
    generate_variants(text)


def _translate_with_retry(text: str) -> str:
    query = urlencode(
        {"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text}
    )
    endpoint = f"https://translate.googleapis.com/translate_a/single?{query}"
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            request = Request(endpoint, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=30) as response:  # noqa: S310
                payload = json.load(response)
            translation = "".join(
                str(part[0]) for part in payload[0] if part and part[0]
            ).strip()
            if translation:
                return translation
        except Exception as error:  # noqa: BLE001
            last_error = error
        time.sleep(min(8.0, 0.5 * (2**attempt)))
    raise RuntimeError(f"翻译失败: {text}") from last_error


def _load_snapshot(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("CET 快照必须是 JSON 数组")
    result: list[dict[str, str]] = []
    required = {
        "level",
        "origin",
        "text",
        "translation_zh",
        "source_name",
        "source_url",
        "source_author",
        "source_item_id",
        "license_name",
        "license_url",
    }
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict) or not required <= item.keys():
            raise ValueError(f"CET 快照第 {index} 项字段不完整")
        result.append({key: str(item[key]) for key in required})
    return result


def _validate_snapshot(snapshot: list[dict[str, str]]) -> None:
    counts = Counter(item["level"] for item in snapshot)
    origin_counts = Counter((item["level"], item["origin"]) for item in snapshot)
    if counts != {"cet4": 3_000, "cet6": 3_000}:
        raise ValueError(f"CET 快照级别数量不正确: {counts}")
    for level in _LEVELS:
        if origin_counts[(level, "authentic")] == 0:
            raise ValueError(f"{level} 缺少真题句")
        if origin_counts[(level, "simulated")] == 0:
            raise ValueError(f"{level} 缺少模拟题句")
    seen: set[str] = set()
    for item in snapshot:
        _validate_sentence(item["text"])
        if not item["translation_zh"].strip():
            raise ValueError(f"句子缺少中文翻译: {item['source_item_id']}")
        digest = normalized_hash(item["text"])
        if digest in seen:
            raise ValueError(f"CET 快照包含重复句: {item['text']}")
        seen.add(digest)


def _remove_existing_cet_rows(connection: sqlite3.Connection) -> None:
    existing = connection.execute(
        "SELECT COUNT(*) FROM top_scenes WHERE key = 'cet'"
    ).fetchone()[0]
    if not existing:
        return
    question_ids = [
        row[0]
        for row in connection.execute(
            """
            SELECT q.id
            FROM question_variants AS q
            JOIN sentences AS s ON s.id = q.sentence_id
            WHERE s.sub_scene_key IN ('cet_cet4', 'cet_cet6')
            """
        )
    ]
    connection.executemany(
        "DELETE FROM aliases WHERE question_variant_id = ?",
        [(question_id,) for question_id in question_ids],
    )
    connection.execute(
        """
        DELETE FROM question_variants
        WHERE sentence_id IN (
            SELECT id FROM sentences
            WHERE sub_scene_key IN ('cet_cet4', 'cet_cet6')
        )
        """
    )
    connection.execute(
        "DELETE FROM sentences WHERE sub_scene_key IN ('cet_cet4', 'cet_cet6')"
    )
    connection.execute("DELETE FROM sub_scenes WHERE top_key = 'cet'")
    connection.execute("DELETE FROM top_scenes WHERE key = 'cet'")


def _insert_cet_catalog(connection: sqlite3.Connection) -> None:
    top_order = connection.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM top_scenes"
    ).fetchone()[0]
    sub_order = connection.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM sub_scenes"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO top_scenes(key, label, sort_order) VALUES ('cet', '四六级考试', ?)",
        (top_order,),
    )
    connection.executemany(
        """
        INSERT INTO sub_scenes(key, top_key, label, quota, sort_order)
        VALUES (?, 'cet', ?, 3000, ?)
        """,
        [
            ("cet_cet4", "四级 CET-4", sub_order),
            ("cet_cet6", "六级 CET-6", sub_order + 1),
        ],
    )


def _insert_snapshot_item(
    connection: sqlite3.Connection, item: dict[str, str]
) -> None:
    text = clean_sentence(item["text"])
    digest = normalized_hash(text)
    sentence_id = f"s_{digest[:16]}"
    collision = connection.execute(
        "SELECT normalized_hash FROM sentences WHERE id = ?", (sentence_id,)
    ).fetchone()
    if collision is not None and collision[0] != digest:
        sentence_id = f"s_{digest[:24]}"
    connection.execute(
        """
        INSERT INTO sentences(
            id, text, translation_zh, sub_scene_key, source_url, source_name,
            source_author, source_item_id, license_name, license_url,
            normalized_hash, random_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sentence_id,
            text,
            item["translation_zh"].strip(),
            _SUB_SCENES[item["level"]],
            item["source_url"],
            item["source_name"],
            item["source_author"],
            item["source_item_id"],
            item["license_name"],
            item["license_url"],
            digest,
            int.from_bytes(bytes.fromhex(digest)[:8], "big")
            & _POSITIVE_63_BIT_MASK,
        ),
    )
    for variant in generate_variants(text):
        variant_id = f"{sentence_id}-{variant.difficulty}"
        connection.execute(
            """
            INSERT INTO question_variants(
                id, sentence_id, difficulty, answer_start, answer_end,
                canonical_answer, answer_word_count, difficulty_score, rationale
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                variant_id,
                sentence_id,
                variant.difficulty,
                variant.answer_start,
                variant.answer_end,
                variant.canonical_answer,
                variant.blank_count,
                variant.score,
                variant.rationale,
            ),
        )
        connection.executemany(
            "INSERT INTO aliases(question_variant_id, alias) VALUES (?, ?)",
            [(variant_id, alias) for alias in variant.aliases],
        )


def _build_quality_report(connection: sqlite3.Connection) -> dict[str, Any]:
    sentence_count = int(connection.execute("SELECT COUNT(*) FROM sentences").fetchone()[0])
    variant_count = int(
        connection.execute("SELECT COUNT(*) FROM question_variants").fetchone()[0]
    )
    scene_counts = dict(
        connection.execute(
            "SELECT sub_scene_key, COUNT(*) FROM sentences GROUP BY sub_scene_key"
        ).fetchall()
    )
    difficulty_counts = dict(
        connection.execute(
            "SELECT difficulty, COUNT(*) FROM question_variants GROUP BY difficulty"
        ).fetchall()
    )
    word_counts = dict(
        connection.execute(
            """
            SELECT CAST(answer_word_count AS TEXT), COUNT(*)
            FROM question_variants
            GROUP BY answer_word_count
            ORDER BY answer_word_count
            """
        ).fetchall()
    )
    source_counts = dict(
        connection.execute(
            "SELECT source_name, COUNT(*) FROM sentences GROUP BY source_name"
        ).fetchall()
    )
    return {
        "gate_status": "passed",
        "sentence_count": sentence_count,
        "variant_count": variant_count,
        "scene_distribution": {
            scene.key: int(scene_counts.get(scene.key, 0)) for scene in SCENES
        },
        "difficulty_distribution": {
            difficulty: int(difficulty_counts.get(difficulty, 0))
            for difficulty in ("easy", "medium", "hard")
        },
        "answer_word_count_distribution": {
            str(length): int(count) for length, count in word_counts.items()
        },
        "duplicate_rate": 0.0,
        "rejected_count": 0,
        "rejection_reasons": {},
        "source_distribution": {
            str(name): int(count) for name, count in sorted(source_counts.items())
        },
    }


def _build_source_manifest(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT source_name, source_url, license_name, license_url, source_author, COUNT(*)
        FROM sentences
        GROUP BY source_name, source_url, license_name, license_url, source_author
        ORDER BY source_name, source_url, source_author
        """
    ).fetchall()
    return [
        {
            "source_name": str(row[0]),
            "source_url": str(row[1]),
            "license_name": str(row[2]),
            "license_url": str(row[3]),
            "source_author": str(row[4]),
            "sentence_count": int(row[5]),
        }
        for row in rows
    ]


def _write_json_atomically(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="构建四六级离线题库扩展")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--base-database", type=Path, required=True)
    extract_parser.add_argument("--paper-repository", type=Path, required=True)
    extract_parser.add_argument("--markdown-repository", type=Path, required=True)
    extract_parser.add_argument("--cet4-simulated", type=Path, required=True)
    extract_parser.add_argument("--cet6-simulated", type=Path, required=True)
    extract_parser.add_argument("--output", type=Path, required=True)

    translate_parser = subparsers.add_parser("translate")
    translate_parser.add_argument("snapshot", type=Path)
    translate_parser.add_argument("--workers", type=int, default=12)

    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--base-database", type=Path, required=True)
    publish_parser.add_argument("--snapshot", type=Path, required=True)
    publish_parser.add_argument("--database", type=Path, required=True)
    publish_parser.add_argument("--report", type=Path, required=True)
    publish_parser.add_argument("--sources", type=Path, required=True)

    arguments = parser.parse_args()
    if arguments.command == "extract":
        snapshot = create_snapshot(
            base_database=arguments.base_database,
            paper_repository=arguments.paper_repository,
            markdown_repository=arguments.markdown_repository,
            cet4_simulated=arguments.cet4_simulated,
            cet6_simulated=arguments.cet6_simulated,
            output=arguments.output,
        )
        print(f"已生成 {len(snapshot)} 条 CET 快照")
    elif arguments.command == "translate":
        translated = translate_snapshot(arguments.snapshot, workers=arguments.workers)
        print(f"已翻译 {translated} 条")
    else:
        publish_extension(
            base_database=arguments.base_database,
            snapshot_path=arguments.snapshot,
            database_path=arguments.database,
            report_path=arguments.report,
            sources_path=arguments.sources,
        )
        print("四六级题库扩展已发布")


if __name__ == "__main__":
    main()
