from __future__ import annotations

import hashlib
import html
import re
import unicodedata

_HTML_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
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
    return _SPACE.sub(" ", text).strip()


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
    cleaned = clean_sentence(text)
    words = _WORD.findall(cleaned)
    if len(words) < 6:
        return "too_short"
    if len(words) > 28 or len(cleaned) > 220:
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
