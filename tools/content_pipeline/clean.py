from __future__ import annotations

import hashlib
import html
import re
import unicodedata

_HTML_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_SAFE_SPEAKER_PREFIX = re.compile(
    r"^(?:[A-Z]{2,}(?:\s+[A-Z]{2,})*|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+):\s+"
)
_SUBTITLE_METADATA = re.compile(
    r"^\d{1,2}:\d{2}:\d{2}(?:[,.]\d{3})?\s*-->\s*\d{1,2}:\d{2}:\d{2}(?:[,.]\d{3})?$"
)
_STAGE_DIRECTION = re.compile(r"^(?:\[[^\]]+\]|\([^\)]+\))$")
_SPEAKER_LABEL = re.compile(r"^(?:SPEAKER|SPK|PERSON)\s*\d*:\s*", re.IGNORECASE)
_QUOTE_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "–": "-",
        "—": "-",
    }
)


def clean_sentence(raw: str) -> str:
    text = html.unescape(raw)
    text = _HTML_TAG.sub(" ", text)
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_TRANSLATION)
    text = _INVISIBLE.sub("", text)
    text = _SPACE.sub(" ", text).strip()
    return _SAFE_SPEAKER_PREFIX.sub("", text)


def normalized_text(text: str) -> str:
    return _SPACE.sub(" ", clean_sentence(text).casefold()).strip()


def normalized_hash(text: str) -> str:
    return hashlib.sha256(normalized_text(text).encode("utf-8")).hexdigest()


_SENSITIVE = re.compile(
    r"\b(?:porn|suicide|self-harm|terrorism|terrorist|rape|murder|abuse|war|weapon|dying|"
    r"attack(?:ed|ing|s)?|kill(?:ed|ing|s)?|violent|violence|air strike|racial slur|"
    r"explicit sex|graphic violence)\b"
    r"|\b(?:fuck(?:ed|ing|er|s)?|motherfucker|shit(?:ty)?|cunt)\b"
    r"|\bkill(?:ed|ing)?\s+(?:my|your|him|her|them)self\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def rejection_reason(text: str) -> str | None:
    raw = _SPACE.sub(" ", _HTML_TAG.sub(" ", html.unescape(text))).strip()
    if _SUBTITLE_METADATA.fullmatch(raw):
        return "subtitle_metadata"
    if _STAGE_DIRECTION.fullmatch(raw):
        return "stage_direction"
    if _SPEAKER_LABEL.match(raw):
        return "speaker_label"
    cleaned = clean_sentence(text)
    words = _WORD.findall(cleaned)
    if len(words) < 5:
        return "too_short"
    if len(words) > 35:
        return "too_long"
    if not re.search(r"[.!?][\"']?$", cleaned):
        return "incomplete"
    if _SENSITIVE.search(cleaned):
        return "sensitive"
    if cleaned.count('"') % 2:
        return "unbalanced_quotes"
    abbreviation_safe = re.sub(
        r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St)\.",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    if re.search(r"[.!?][\"']?\s+[\"']?[A-Z]", abbreviation_safe):
        return "multiple_sentences"
    if sum(character.isdigit() for character in cleaned) > len(cleaned) * 0.2:
        return "mostly_numeric"
    if len({word.casefold() for word in words}) < max(4, len(words) // 3):
        return "low_quality"
    return None
