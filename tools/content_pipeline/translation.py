from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Protocol

from tools.content_pipeline.work_database import WorkDatabase

OPUS_MT_MODEL = "Helsinki-NLP/opus-mt-en-zh"
_NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_CURRENCY_WORDS = re.compile(
    r"(?:[$€£¥￥]|\b(?:USD|EUR|GBP|CNY|RMB|dollars?|euros?|pounds?|yuan)\b|美元|美金|欧元|英镑|人民币|元)",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"(?:%|％|\bpercent(?:age)?\b|百分之)", re.IGNORECASE)
_IMPORT_FIELDS = {"item_id", "translation_zh", "review_note"}


class Translator(Protocol):
    model_version: str

    def translate_batch(self, texts: list[str]) -> list[str]: ...


class TranslationImportError(ValueError):
    pass


class OpusMtTranslator:
    def __init__(
        self,
        *,
        batch_size: int = 32,
        revision: str = "main",
        device: str | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("翻译批次大小必须大于零")
        self.batch_size = batch_size
        self.revision = revision
        self.device = device
        self.model_version = f"{OPUS_MT_MODEL}@{revision}"
        self._tokenizer: object | None = None
        self._model: object | None = None

    def translate_batch(self, texts: list[str]) -> list[str]:
        self._load()
        tokenizer = self._tokenizer
        model = self._model
        if tokenizer is None or model is None:
            raise RuntimeError("OPUS-MT 模型加载失败")
        translations: list[str] = []
        for offset in range(0, len(texts), self.batch_size):
            batch = texts[offset : offset + self.batch_size]
            encoded = tokenizer(batch, return_tensors="pt", padding=True, truncation=True)
            if self.device:
                encoded = encoded.to(self.device)
            generated = model.generate(**encoded)
            translations.extend(tokenizer.batch_decode(generated, skip_special_tokens=True))
        return translations

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        device = self.device
        if device is None:
            if torch.backends.mps.is_available():
                device = "mps"
            elif torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"
            self.device = device
        tokenizer = AutoTokenizer.from_pretrained(OPUS_MT_MODEL, revision=self.revision)
        model = AutoModelForSeq2SeqLM.from_pretrained(OPUS_MT_MODEL, revision=self.revision)
        model.to(device)
        model.eval()
        resolved_revision = getattr(model.config, "_commit_hash", None) or self.revision
        self.model_version = f"{OPUS_MT_MODEL}@{resolved_revision}"
        self._tokenizer = tokenizer
        self._model = model


def validate_translation(source: str, translation: str) -> tuple[str, ...]:
    source = unicodedata.normalize("NFKC", source).strip()
    translation = unicodedata.normalize("NFKC", translation).strip()
    if not translation:
        return ("empty_translation",)

    issues: list[str] = []
    han_count = len(_HAN.findall(translation))
    latin_count = sum(len(word) for word in _LATIN_WORD.findall(translation))
    if han_count / max(han_count + latin_count, 1) < 0.35:
        issues.append("low_chinese_ratio")
    if _NUMBER.findall(source) != _NUMBER.findall(translation):
        issues.append("number_mismatch")
    if _CURRENCY_WORDS.search(source) and not _CURRENCY_WORDS.search(translation):
        issues.append("money_mismatch")
    if _PERCENT.search(source) and not _PERCENT.search(translation):
        issues.append("percent_mismatch")

    english_words = _LATIN_WORD.findall(translation)
    if len(english_words) >= 2 or any(len(word) >= 8 for word in english_words):
        issues.append("english_residue")

    source_length = len(re.sub(r"\s+", "", source))
    translation_length = len(re.sub(r"\s+", "", translation))
    if source_length >= 20:
        length_ratio = translation_length / source_length
        if length_ratio < 0.12 or length_ratio > 3.0:
            issues.append("abnormal_length")
    return tuple(issues)


def run_translation_stage(
    database: WorkDatabase,
    translator: Translator,
    *,
    batch_size: int = 32,
) -> int:
    if batch_size < 1:
        raise ValueError("翻译批次大小必须大于零")
    processed = 0
    while batch := database.claim_translation_batch(batch_size):
        translations = translator.translate_batch([item.text for item in batch])
        if len(translations) != len(batch):
            raise RuntimeError(
                f"翻译器返回数量异常: 期望 {len(batch)} 条，实际 {len(translations)} 条"
            )
        database.checkpoint_translation_batch(
            [
                (item.id, translation, validate_translation(item.text, translation))
                for item, translation in zip(batch, translations, strict=True)
            ],
            model_version=translator.model_version,
        )
        processed += len(batch)
    return processed


def export_llm_repairs(database: WorkDatabase, path: str | Path) -> int:
    repairs = database.translation_repairs()
    with Path(path).open("w", encoding="utf-8", newline="\n") as output:
        for repair in repairs:
            record = {
                "item_id": repair.item.id,
                "source": repair.item.text,
                "draft": repair.draft,
                "issues": list(repair.issues),
                "top_scene": repair.top_scene,
                "sub_scene": repair.sub_scene,
            }
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return len(repairs)


def import_llm_repairs(database: WorkDatabase, path: str | Path) -> int:
    completed = 0
    repair_sources = {repair.item.id: repair.item.text for repair in database.translation_repairs()}
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            record = _parse_import_record(line, line_number)
            item_id = record["item_id"]
            if item_id not in repair_sources:
                raise TranslationImportError(f"第 {line_number} 行引用的条目不可修正")
            issues = validate_translation(
                repair_sources[item_id],
                record["translation_zh"],
            )
            try:
                accepted = database.apply_translation_repair(
                    item_id,
                    translation=record["translation_zh"],
                    issues=issues,
                    review_note=record["review_note"],
                )
            except ValueError as error:
                raise TranslationImportError(f"第 {line_number} 行引用的条目不可修正") from error
            completed += int(accepted)
    return completed


def _parse_import_record(line: str, line_number: int) -> dict[str, int | str]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as error:
        raise TranslationImportError(f"第 {line_number} 行不是有效 JSON 对象") from error
    if not isinstance(record, dict) or set(record) != _IMPORT_FIELDS:
        raise TranslationImportError(f"第 {line_number} 行字段不符合修正格式")
    item_id = record["item_id"]
    translation = record["translation_zh"]
    review_note = record["review_note"]
    if (
        not isinstance(item_id, int)
        or isinstance(item_id, bool)
        or item_id < 1
        or not isinstance(translation, str)
        or not isinstance(review_note, str)
    ):
        raise TranslationImportError(f"第 {line_number} 行字段类型不符合修正格式")
    return {"item_id": item_id, "translation_zh": translation, "review_note": review_note}
