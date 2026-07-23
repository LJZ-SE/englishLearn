from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

from tools.content_pipeline.work_database import WorkDatabase

OPUS_MT_MODEL = "Helsinki-NLP/opus-mt-en-zh"
_NUMBER = re.compile(
    r"(?<![A-Za-z0-9])\d+(?:[.,:]\d+)*(?:st|nd|rd|th)?"
    r"(?![A-Za-z0-9]|[.,:]\d)",
    re.IGNORECASE,
)
_NUMBER_SCALE = re.compile(
    r"^\s*(thousand|million|billion|千|万|亿)",
    re.IGNORECASE,
)
_GROUPED_DIGIT_SPACE = re.compile(r"(?<=\d)\s+(?=\d{3}(?:\D|$))")
_ATTACHED_MEASUREMENT_UNIT = re.compile(
    r"(?<=\d)(?=(?:km|miles?|kg|kilograms?|cm|centimeters?)\b)",
    re.IGNORECASE,
)
_SPACED_DECIMAL_POINT = re.compile(r"(?<=\d)\.\s+(?=\d)")
_SPACED_LIST_POINT = re.compile(r"(?<=\d)\.\s+(?=\d+\s+[A-Z][A-Za-z]*s\b)")
_SPACED_TIME_POINT = re.compile(
    r"(?<=\d)\.\s+(?=\d{2}\s*(?:a\.?m\.?|p\.?m\.?))",
    re.IGNORECASE,
)
_SPACED_GROUPING_COMMA = re.compile(r"(?<=\d),\s+(?=\d{3}(?:\D|$))")
_ALPHANUMERIC_CODE = re.compile(
    r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*\d)[A-Za-z][A-Za-z0-9]*(?![A-Za-z0-9])"
)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_CURRENCY_PATTERNS = {
    "USD": re.compile(
        r"(?:\$|\b(?:USD|US dollars?|dollars?)\b|美元|美金|加拿大元|新加坡元|"
        r"澳元|港元|新西兰元)",
        re.IGNORECASE,
    ),
    "EUR": re.compile(r"(?:€|\b(?:EUR|euros?)\b|欧元)", re.IGNORECASE),
    "GBP": re.compile(r"(?:£|\b(?:GBP|pounds?)\b|英镑)", re.IGNORECASE),
    "CNY": re.compile(r"(?:\b(?:CNY|RMB|yuan|renminbi)\b|人民币)", re.IGNORECASE),
    "JPY": re.compile(r"(?:\b(?:JPY|yen)\b|日元)", re.IGNORECASE),
    "AMBIGUOUS_YEN": re.compile(r"[¥￥]"),
}
_PERCENT = re.compile(r"(?:%|％|\bpercent(?:age)?\b|百分(?:之|比))", re.IGNORECASE)
_EXPLICIT_GBP = re.compile(r"(?:£|\bGBP\b|英镑)", re.IGNORECASE)
_EXPLICIT_JPY = re.compile(r"(?:[¥￥]|\bJPY\b|日元)", re.IGNORECASE)
_POUND_WEIGHT_CONTEXT = re.compile(
    r"(?:\b(?:weigh(?:s|ed|ing)?|lose|lost|losing|gain(?:s|ed|ing)?|weight)\b"
    r".{0,48}\bpounds?\b|\bpounds?\b.{0,48}\b(?:heavier|lighter|weight)\b|"
    r"\b\d+(?:\.\d+)?\s+pounds?\b.{0,80}\b(?:kg|kilograms?|cm|centimeters?|years? old)\b)",
    re.IGNORECASE,
)
_NON_CNY_YUAN = re.compile(r"(?:加拿大元|新加坡元|澳元|港元|新西兰元|美元|欧元|日元)")
_GENERIC_CNY_YUAN = re.compile(
    r"(?:\d+(?:[.,]\d+)*|[一二三四五六七八九十百千万亿两]+|多少|几)\s*元"
)
_YEN_VENUE_NAME = re.compile(r"\bYen\s+(?:Restaurant|Cafe|Hotel)\b", re.IGNORECASE)
_YEN_PERSON_NAME = re.compile(r"\b(?!Japanese\b)[A-Z][a-z]+\s+Yen\b")
_EUR_NON_CURRENCY = re.compile(r"\bEUR\s+(?:PhD|doctoral)\b", re.IGNORECASE)
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
    english_words = _untranslated_english_words(source, translation)
    latin_count = sum(len(word) for word in english_words)
    if han_count / max(han_count + latin_count, 1) < 0.35:
        issues.append("low_chinese_ratio")
    if _has_number_mismatch(source, translation):
        issues.append("number_mismatch")
    source_currencies = _currency_categories(source)
    if source_currencies != _currency_categories(translation):
        issues.append("currency_mismatch")
    if bool(_PERCENT.search(source)) != bool(_PERCENT.search(translation)):
        issues.append("percentage_mismatch")

    if len(english_words) >= 2 or any(len(word) >= 8 for word in english_words):
        issues.append("english_residue")

    source_length = len(re.sub(r"\s+", "", source))
    translation_length = len(re.sub(r"\s+", "", translation))
    if source_length:
        length_ratio = translation_length / source_length
        too_long = length_ratio > 3.0 and (source_length >= 20 or translation_length > 24)
        if length_ratio < 0.12 or too_long:
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
    while claimed := database.claim_translation_batch(batch_size):
        batch = claimed.items
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
            selection_generation=claimed.selection_generation,
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


def _currency_categories(text: str) -> frozenset[str]:
    categories = {
        currency for currency, pattern in _CURRENCY_PATTERNS.items() if pattern.search(text)
    }
    # pound 既可能表示英镑，也可能表示重量；有明确体重语境且没有货币符号时不算币种。
    if (
        "GBP" in categories
        and not _EXPLICIT_GBP.search(text)
        and _POUND_WEIGHT_CONTEXT.search(text)
    ):
        categories.remove("GBP")
    if (
        "JPY" in categories
        and not _EXPLICIT_JPY.search(text)
        and (_YEN_VENUE_NAME.search(text) or _YEN_PERSON_NAME.search(text))
    ):
        categories.remove("JPY")
    if "EUR" in categories and _EUR_NON_CURRENCY.search(text):
        categories.remove("EUR")
    if _GENERIC_CNY_YUAN.search(_NON_CNY_YUAN.sub("", text)):
        categories.add("CNY")
    return frozenset(categories)


def _has_number_mismatch(source: str, translation: str) -> bool:
    source_numbers = _number_signatures(source)
    if not source_numbers:
        return False
    translation_numbers = _number_signatures(translation)
    return any(
        translation_numbers[signature] < count
        for signature, count in source_numbers.items()
    )


def _untranslated_english_words(source: str, translation: str) -> list[str]:
    source_words = {word.casefold() for word in _LATIN_WORD.findall(source)}
    without_urls = _URL.sub("", translation)
    candidates = _LATIN_WORD.findall(_ALPHANUMERIC_CODE.sub("", without_urls))
    return [
        word
        for word in candidates
        if not (
            word.casefold() in source_words
            and (word[0].isupper() or any(character.isupper() for character in word[1:]))
        )
    ]


def _number_signatures(text: str) -> Counter[str]:
    text = _ATTACHED_MEASUREMENT_UNIT.sub(" ", text)
    text = _SPACED_LIST_POINT.sub(" ", text)
    text = _SPACED_TIME_POINT.sub(":", text)
    text = _SPACED_DECIMAL_POINT.sub(".", text)
    text = _SPACED_GROUPING_COMMA.sub(",", text)
    text = _GROUPED_DIGIT_SPACE.sub("", text)
    signatures: Counter[str] = Counter()
    for match in _NUMBER.finditer(text):
        token = re.sub(r"(?:st|nd|rd|th)$", "", match.group(), flags=re.IGNORECASE)
        if ":" in token:
            signatures.update(_plain_number_signature(part) for part in token.split(":"))
            continue
        if token.count(".") > 1:
            signatures[f"version:{token}"] += 1
            continue
        try:
            value = Decimal(token.replace(",", ""))
        except InvalidOperation:
            continue
        scale_match = _NUMBER_SCALE.match(text[match.end() :])
        if scale_match is not None:
            value *= {
                "thousand": Decimal(1_000),
                "million": Decimal(1_000_000),
                "billion": Decimal(1_000_000_000),
                "千": Decimal(1_000),
                "万": Decimal(10_000),
                "亿": Decimal(100_000_000),
            }[scale_match.group(1).casefold()]
        signatures[_decimal_signature(value)] += 1
    return signatures


def _plain_number_signature(token: str) -> str:
    try:
        return _decimal_signature(Decimal(token.replace(",", "")))
    except InvalidOperation:
        return f"literal:{token}"


def _decimal_signature(value: Decimal) -> str:
    normalized = value.normalize()
    return f"number:{format(normalized, 'f')}"


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
