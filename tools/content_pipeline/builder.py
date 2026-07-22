from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.content_pipeline.clean import clean_sentence, normalized_hash
from tools.content_pipeline.content_schema import initialize_content_schema
from tools.content_pipeline.models import BuildResult, QuestionVariant
from tools.content_pipeline.scenes import SCENES, SUB_SCENES
from tools.content_pipeline.work_database import WorkDatabase

_DIFFICULTIES = ("easy", "medium", "hard")
_POSITIVE_63_BIT_MASK = (1 << 63) - 1


class BuildError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _PublishRow:
    work_item_id: int
    text: str
    translation_zh: str
    sub_scene_key: str
    source_url: str
    source_name: str
    source_author: str
    source_item_id: str
    license_name: str
    license_url: str
    digest: str
    variants: tuple[QuestionVariant, QuestionVariant, QuestionVariant]


@dataclass(frozen=True, slots=True)
class _LegacyIds:
    sentence_ids: dict[str, str]
    question_ids: dict[tuple[str, str], str]
    aliases: dict[tuple[str, str], tuple[str, ...]]
    all_sentence_ids: frozenset[str]
    all_question_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class _OutputBackup:
    target: Path
    path: Path | None
    payload: bytes | None


def stable_sentence_id(text: str) -> str:
    return f"s_{normalized_hash(text)[:16]}"


def build_database(
    work_db: WorkDatabase | str | Path,
    database_path: Path,
    report_path: Path,
    sources_path: Path,
    *,
    preserve_ids_from: Path | None = None,
) -> BuildResult:
    database = work_db if isinstance(work_db, WorkDatabase) else WorkDatabase(work_db)
    rows = _load_publish_rows(database)
    if not rows:
        raise BuildError("工作库没有可发布的 variants 记录")
    legacy = _load_legacy_ids(preserve_ids_from)
    sentence_ids = _allocate_sentence_ids(rows, legacy)

    for path in (database_path, report_path, sources_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    database_temporary = database_path.with_suffix(database_path.suffix + ".tmp")
    report_temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    sources_temporary = sources_path.with_suffix(sources_path.suffix + ".tmp")
    for temporary in (database_temporary, report_temporary, sources_temporary):
        if temporary.exists():
            temporary.unlink()

    phrase_lengths: Counter[int] = Counter()
    difficulty_counts: Counter[str] = Counter()
    scene_counts: Counter[str] = Counter()
    source_counts: Counter[tuple[str, str, str, str, str]] = Counter()
    try:
        with closing(sqlite3.connect(database_temporary)) as connection, connection:
            initialize_content_schema(connection)
            preserved_question_ids = {
                legacy.question_ids[(row.digest, difficulty)]
                for row in rows
                for difficulty in _DIFFICULTIES
                if (row.digest, difficulty) in legacy.question_ids
            }
            used_question_ids = set(legacy.all_question_ids - preserved_question_ids)
            for row in rows:
                sentence_id = sentence_ids[row.digest]
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
                        row.text,
                        row.translation_zh,
                        row.sub_scene_key,
                        row.source_url,
                        row.source_name,
                        row.source_author,
                        row.source_item_id,
                        row.license_name,
                        row.license_url,
                        row.digest,
                        _random_key(row.digest),
                    ),
                )
                for variant in row.variants:
                    key = (row.digest, variant.difficulty)
                    variant_id = legacy.question_ids.get(
                        key, f"{sentence_id}-{variant.difficulty}"
                    )
                    if variant_id in used_question_ids:
                        raise BuildError(f"题目 ID 冲突: {variant_id}")
                    used_question_ids.add(variant_id)
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
                    aliases = set(variant.aliases)
                    aliases.update(legacy.aliases.get(key, ()))
                    connection.executemany(
                        "INSERT INTO aliases(question_variant_id, alias) VALUES (?, ?)",
                        [(variant_id, alias) for alias in sorted(aliases)],
                    )
                    phrase_lengths[variant.blank_count] += 1
                    difficulty_counts[variant.difficulty] += 1
                scene_counts[row.sub_scene_key] += 1
                source_counts[
                    (
                        row.source_name,
                        row.source_url,
                        row.license_name,
                        row.license_url,
                        row.source_author,
                    )
                ] += 1
            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise BuildError(f"候选库外键检查失败: {foreign_key_errors[:3]}")
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise BuildError(f"候选库完整性检查失败: {integrity}")

        report = {
            "gate_status": "passed",
            "sentence_count": len(rows),
            "variant_count": len(rows) * 3,
            "scene_distribution": {
                scene.key: scene_counts[scene.key] for scene in SCENES
            },
            "difficulty_distribution": {
                difficulty: difficulty_counts[difficulty] for difficulty in _DIFFICULTIES
            },
            "answer_word_count_distribution": {
                str(length): phrase_lengths[length] for length in sorted(phrase_lengths)
            },
            "duplicate_rate": 0.0,
            "rejected_count": 0,
            "rejection_reasons": {},
            "source_distribution": {
                name: sum(count for key, count in source_counts.items() if key[0] == name)
                for name in sorted({key[0] for key in source_counts})
            },
        }
        source_manifest = [
            {
                "source_name": key[0],
                "source_url": key[1],
                "license_name": key[2],
                "license_url": key[3],
                "source_author": key[4],
                "sentence_count": count,
            }
            for key, count in sorted(source_counts.items())
        ]
        report_temporary.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        sources_temporary.write_text(
            json.dumps(source_manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _validate_temporary_artifacts(
            database_temporary,
            report_temporary,
            sources_temporary,
            sentence_count=len(rows),
            variant_count=len(rows) * 3,
        )
    except Exception:
        _cleanup_paths((database_temporary, report_temporary, sources_temporary))
        raise

    _commit_outputs_atomically(
        (
            (database_temporary, database_path),
            (report_temporary, report_path),
            (sources_temporary, sources_path),
        )
    )

    return BuildResult(
        sentence_count=len(rows),
        variant_count=len(rows) * 3,
        rejected_count=0,
        database=database_path,
        report=report_path,
        sources=sources_path,
    )


def _load_publish_rows(database: WorkDatabase) -> list[_PublishRow]:
    with closing(database.connect()) as connection:
        connection.execute("BEGIN")
        selected_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM stage_results WHERE stage = 'select'"
            ).fetchone()[0]
        )
        generation_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM stage_generations WHERE stage = 'select'"
            ).fetchone()[0]
        )
        rows = connection.execute(
            """
            SELECT r.id, r.text, r.source_url, r.source_name, r.source_author,
                   r.source_item_id, r.license_name, r.license_url,
                   cleaned.payload_json, selected.payload_json,
                   translated.payload_json, variants.payload_json
            FROM raw_items AS r
            JOIN stage_results AS cleaned
              ON cleaned.item_id = r.id AND cleaned.stage = 'clean'
            JOIN stage_results AS selected
              ON selected.item_id = r.id AND selected.stage = 'select'
            LEFT JOIN stage_results AS translated
              ON translated.item_id = r.id AND translated.stage = 'translate'
            LEFT JOIN stage_results AS variants
              ON variants.item_id = r.id AND variants.stage = 'variants'
            LEFT JOIN rejections AS rejected ON rejected.item_id = r.id
            WHERE rejected.item_id IS NULL
            ORDER BY r.id
            """
        ).fetchall()
    if selected_count != len(rows):
        raise BuildError("select 快照包含被拒绝或缺少 clean 前置阶段的条目")
    if selected_count and generation_count != 1:
        raise BuildError("select 快照缺少唯一 generation")

    published: list[_PublishRow] = []
    seen_hashes: set[str] = set()
    for raw in rows:
        item_id = int(raw[0])
        if raw[10] is None:
            raise BuildError(f"条目 {item_id} 缺少 translate 阶段结果")
        if raw[11] is None:
            raise BuildError(f"条目 {item_id} 缺少 variants 阶段结果")
        clean_payload = _payload(raw[8], item_id, "clean")
        select_payload = _payload(raw[9], item_id, "select")
        translate_payload = _payload(raw[10], item_id, "translate")
        variant_payload = _payload(raw[11], item_id, "variants")
        text_value = clean_payload.get("clean_text")
        text = clean_sentence(str(text_value if isinstance(text_value, str) else raw[1]))
        translation = translate_payload.get("translation_zh")
        if not isinstance(translation, str) or not translation.strip():
            raise BuildError(f"条目 {item_id} 的 translation_zh 为空")
        issues = translate_payload.get("issues")
        if not isinstance(issues, list) or issues:
            raise BuildError(f"条目 {item_id} 的翻译仍包含未解决 issues")
        top_scene = select_payload.get("top_scene")
        sub_scene = select_payload.get("sub_scene")
        if not isinstance(top_scene, str) or not isinstance(sub_scene, str):
            raise BuildError(f"条目 {item_id} 的场景字段无效")
        definition = SUB_SCENES.get(sub_scene)
        if definition is None or definition.top_key != top_scene:
            raise BuildError(f"条目 {item_id} 的 top_scene/sub_scene 不匹配")
        provenance = tuple(str(value).strip() for value in raw[2:8])
        if not all(provenance):
            raise BuildError(f"条目 {item_id} 缺少来源或许可字段")
        digest = normalized_hash(text)
        if digest in seen_hashes:
            raise BuildError(f"条目 {item_id} 与其他发布句规范化重复")
        seen_hashes.add(digest)
        published.append(
            _PublishRow(
                work_item_id=item_id,
                text=text,
                translation_zh=translation.strip(),
                sub_scene_key=sub_scene,
                source_url=provenance[0],
                source_name=provenance[1],
                source_author=provenance[2],
                source_item_id=provenance[3],
                license_name=provenance[4],
                license_url=provenance[5],
                digest=digest,
                variants=_parse_variants(text, variant_payload, item_id),
            )
        )
    return published


def _payload(raw: str, item_id: int, stage: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise BuildError(f"条目 {item_id} 的 {stage} payload 不是合法 JSON") from error
    if not isinstance(payload, dict):
        raise BuildError(f"条目 {item_id} 的 {stage} payload 必须是对象")
    return payload


def _parse_variants(
    text: str, payload: dict[str, Any], item_id: int
) -> tuple[QuestionVariant, QuestionVariant, QuestionVariant]:
    raw_variants = payload.get("variants")
    if not isinstance(raw_variants, list) or len(raw_variants) != 3:
        raise BuildError(f"条目 {item_id} 的 variants 必须恰好包含三个版本")
    parsed: dict[str, QuestionVariant] = {}
    for raw in raw_variants:
        if not isinstance(raw, dict):
            raise BuildError(f"条目 {item_id} 的 variant 必须是对象")
        difficulty = raw.get("difficulty")
        start = raw.get("answer_start")
        end = raw.get("answer_end")
        answer = raw.get("canonical_answer")
        word_count = raw.get("answer_word_count")
        score = raw.get("difficulty_score")
        rationale = raw.get("rationale")
        aliases = raw.get("aliases")
        if difficulty not in _DIFFICULTIES or difficulty in parsed:
            raise BuildError(f"条目 {item_id} 的 variants difficulty 重复或无效")
        if not _plain_int(start) or not _plain_int(end) or not _plain_int(word_count):
            raise BuildError(f"条目 {item_id} 的 variant 整数字段无效")
        if not isinstance(answer, str) or not answer:
            raise BuildError(f"条目 {item_id} 的 canonical_answer 为空")
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(score)
        ):
            raise BuildError(f"条目 {item_id} 的 difficulty_score 无效")
        if not isinstance(rationale, str) or not rationale.strip():
            raise BuildError(f"条目 {item_id} 的 rationale 为空")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise BuildError(f"条目 {item_id} 的 aliases 无效")
        if start < 0 or end <= start or end > len(text) or text[start:end] != answer:
            raise BuildError(f"条目 {item_id} 的答案区间无法精确填回原句")
        if not 1 <= word_count <= 4:
            raise BuildError(f"条目 {item_id} 的 answer_word_count 必须为 1 到 4")
        if word_count != len(answer.split()):
            raise BuildError(f"条目 {item_id} 的 answer_word_count 与答案不一致")
        parsed[difficulty] = QuestionVariant(
            difficulty=difficulty,
            answer_start=start,
            answer_end=end,
            canonical_answer=answer,
            blank_count=word_count,
            score=float(score),
            rationale=rationale.strip(),
            aliases=tuple(sorted(set(aliases))),
        )
    ordered = tuple(parsed[difficulty] for difficulty in _DIFFICULTIES)
    if not (ordered[0].score < ordered[1].score < ordered[2].score):
        raise BuildError(f"条目 {item_id} 的三个难度分值必须严格递增")
    if len({variant.canonical_answer.casefold() for variant in ordered}) != 3:
        raise BuildError(f"条目 {item_id} 的三个版本答案必须不同")
    return ordered  # type: ignore[return-value]


def _plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _load_legacy_ids(path: Path | None) -> _LegacyIds:
    if path is None:
        return _LegacyIds({}, {}, {}, frozenset(), frozenset())
    if not path.is_file():
        raise BuildError(f"旧题库不存在: {path}")
    try:
        with closing(sqlite3.connect(path)) as connection:
            sentence_rows = connection.execute(
                "SELECT normalized_hash, id FROM sentences"
            ).fetchall()
            question_rows = connection.execute(
                """
                SELECT s.normalized_hash, q.difficulty, q.id
                FROM question_variants AS q
                JOIN sentences AS s ON s.id = q.sentence_id
                """
            ).fetchall()
            alias_rows = connection.execute(
                """
                SELECT s.normalized_hash, q.difficulty, a.alias
                FROM aliases AS a
                JOIN question_variants AS q ON q.id = a.question_variant_id
                JOIN sentences AS s ON s.id = q.sentence_id
                ORDER BY a.id
                """
            ).fetchall()
    except sqlite3.Error as error:
        raise BuildError(f"无法读取旧题库 ID 映射: {error}") from error
    sentence_ids = {str(digest): str(sentence_id) for digest, sentence_id in sentence_rows}
    question_ids = {
        (str(digest), str(difficulty)): str(question_id)
        for digest, difficulty, question_id in question_rows
    }
    aliases: dict[tuple[str, str], list[str]] = {}
    for digest, difficulty, alias in alias_rows:
        aliases.setdefault((str(digest), str(difficulty)), []).append(str(alias))
    return _LegacyIds(
        sentence_ids=sentence_ids,
        question_ids=question_ids,
        aliases={key: tuple(dict.fromkeys(values)) for key, values in aliases.items()},
        all_sentence_ids=frozenset(str(row[1]) for row in sentence_rows),
        all_question_ids=frozenset(str(row[2]) for row in question_rows),
    )


def _allocate_sentence_ids(
    rows: list[_PublishRow], legacy: _LegacyIds
) -> dict[str, str]:
    allocated: dict[str, str] = {}
    used_ids = set(legacy.all_sentence_ids)
    for row in rows:
        preserved = legacy.sentence_ids.get(row.digest)
        if preserved is not None:
            allocated[row.digest] = preserved
    for row in sorted(rows, key=lambda item: item.digest):
        if row.digest in allocated:
            continue
        candidate = f"s_{row.digest[:16]}"
        if candidate in used_ids:
            candidate = f"s_{row.digest[:24]}"
        if candidate in used_ids:
            raise BuildError(f"稳定 sentence ID 在 24 位仍冲突: {candidate}")
        allocated[row.digest] = candidate
        used_ids.add(candidate)
    return allocated


def _random_key(digest: str) -> int:
    return int.from_bytes(bytes.fromhex(digest)[:8], "big") & _POSITIVE_63_BIT_MASK


def _validate_temporary_artifacts(
    database: Path,
    report: Path,
    sources: Path,
    *,
    sentence_count: int,
    variant_count: int,
) -> None:
    with closing(sqlite3.connect(database)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise BuildError("候选临时数据库完整性检查失败")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise BuildError("候选临时数据库外键检查失败")
        counts = (
            int(connection.execute("SELECT COUNT(*) FROM sentences").fetchone()[0]),
            int(
                connection.execute("SELECT COUNT(*) FROM question_variants").fetchone()[0]
            ),
        )
    if counts != (sentence_count, variant_count):
        raise BuildError(f"候选临时数据库计数不一致: {counts}")
    try:
        report_payload = json.loads(report.read_text(encoding="utf-8"))
        source_payload = json.loads(sources.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError("候选报告或来源清单无法重新读取") from error
    if (
        report_payload.get("sentence_count") != sentence_count
        or report_payload.get("variant_count") != variant_count
    ):
        raise BuildError("候选报告计数与数据库不一致")
    if not isinstance(source_payload, list) or sum(
        int(item.get("sentence_count", 0))
        for item in source_payload
        if isinstance(item, dict)
    ) != sentence_count:
        raise BuildError("候选来源清单计数与数据库不一致")


def _commit_outputs_atomically(outputs: tuple[tuple[Path, Path], ...]) -> None:
    temporaries = tuple(temporary for temporary, _ in outputs)
    try:
        backups = _create_output_backups(tuple(target for _, target in outputs))
    except Exception:
        _cleanup_paths(temporaries)
        raise

    try:
        for temporary, target in outputs:
            temporary.replace(target)
    except Exception as error:
        rollback_errors = _restore_outputs(backups)
        cleanup_errors = _cleanup_paths(
            (*temporaries, *(backup.path for backup in backups if backup.path is not None))
        )
        if rollback_errors:
            detail = "; ".join((*rollback_errors, *cleanup_errors))
            raise BuildError(f"候选三文件提交失败且回滚不完整: {detail}") from error
        raise

    backup_paths = tuple(backup.path for backup in backups if backup.path is not None)
    cleanup_errors = _cleanup_paths(backup_paths)
    if not cleanup_errors:
        return

    rollback_errors = _restore_outputs(backups)
    residual_errors = _cleanup_paths((*temporaries, *backup_paths))
    if rollback_errors:
        detail = "; ".join((*cleanup_errors, *rollback_errors, *residual_errors))
        raise BuildError(f"清理备份失败且候选回滚不完整: {detail}")
    detail = "; ".join((*cleanup_errors, *residual_errors))
    raise BuildError(f"清理备份失败，已恢复全部旧目标: {detail}")


def _create_output_backups(targets: tuple[Path, ...]) -> tuple[_OutputBackup, ...]:
    backups: list[_OutputBackup] = []
    try:
        for target in targets:
            if not target.exists():
                backups.append(_OutputBackup(target, None, None))
                continue
            payload = target.read_bytes()
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".bak", dir=target.parent
            )
            backup_path = Path(raw_path)
            backups.append(_OutputBackup(target, backup_path, payload))
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
    except Exception:
        _cleanup_paths(
            tuple(backup.path for backup in backups if backup.path is not None)
        )
        raise
    return tuple(backups)


def _restore_outputs(backups: tuple[_OutputBackup, ...]) -> tuple[str, ...]:
    errors: list[str] = []
    for backup in backups:
        try:
            if backup.payload is None:
                if backup.target.exists():
                    backup.target.unlink()
                continue
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{backup.target.name}.",
                suffix=".restore",
                dir=backup.target.parent,
            )
            restore_path = Path(raw_path)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(backup.payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                restore_path.replace(backup.target)
            except Exception:
                _cleanup_paths((restore_path,))
                raise
        except Exception as error:
            errors.append(f"恢复 {backup.target} 失败: {error}")
    return tuple(errors)


def _cleanup_paths(paths: tuple[Path, ...]) -> tuple[str, ...]:
    errors: list[str] = []
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError as error:
            errors.append(f"清理 {path} 失败: {error}")
    return tuple(errors)
