from __future__ import annotations

import sqlite3
from typing import Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from listening_cloze.infrastructure.dictionary import DictionaryEntry

TAG_LABELS = {
    "zk": "中考",
    "gk": "高考",
    "cet4": "CET-4",
    "cet6": "CET-6",
    "ky": "考研",
    "ielts": "雅思",
    "toefl": "托福",
    "gre": "GRE",
}
TAG_ORDER = {
    "gk": 10,
    "cet4": 20,
    "cet6": 30,
    "ky": 40,
    "ielts": 50,
    "toefl": 60,
    "gre": 70,
    "zk": 80,
}
EXCHANGE_LABELS = {
    "p": "过去式",
    "d": "过去分词",
    "i": "现在分词",
    "3": "第三人称",
    "r": "比较级",
    "t": "最高级",
    "s": "复数",
    "0": "原形",
    "1": "原形变化",
}


class DictionaryDataSource(Protocol):
    def lookup(self, term: str, *, limit: int = 12) -> tuple[DictionaryEntry, ...]: ...


class DictionaryViewModel(QObject):
    dataChanged = Signal()

    def __init__(
        self,
        repository: DictionaryDataSource,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._repository = repository
        self._visible = False
        self._query = ""
        self._entries: list[dict[str, object]] = []
        self._result_text = ""
        self._error_text = ""

    @Property(bool, notify=dataChanged)
    def visible(self) -> bool:
        return self._visible

    @Property(str, notify=dataChanged)
    def query(self) -> str:
        return self._query

    @Property("QVariantList", notify=dataChanged)
    def entries(self) -> list[dict[str, object]]:
        return [dict(entry) for entry in self._entries]

    @Property(str, notify=dataChanged)
    def resultText(self) -> str:
        return self._result_text

    @Property(str, notify=dataChanged)
    def errorText(self) -> str:
        return self._error_text

    @Slot(str)
    def lookup(self, term: str) -> None:
        self._query = " ".join(term.split())
        self._visible = True
        try:
            results = self._repository.lookup(self._query)
            self._entries = [_entry_to_qml(entry) for entry in results]
            self._result_text = (
                f"找到 {len(results)} 个词条" if results else "没有找到该词条"
            )
            self._error_text = ""
        except (OSError, RuntimeError, sqlite3.Error) as error:
            self._entries = []
            self._result_text = "词典暂时无法使用"
            self._error_text = str(error)
        self.dataChanged.emit()

    @Slot()
    def close(self) -> None:
        self._visible = False
        self.dataChanged.emit()


def _entry_to_qml(entry: DictionaryEntry) -> dict[str, object]:
    tags = sorted(
        (tag for tag in entry.tags if tag in TAG_LABELS),
        key=lambda tag: (TAG_ORDER.get(tag, 999), tag),
    )
    return {
        "word": entry.word,
        "phonetic": f"/{entry.phonetic}/" if entry.phonetic else "",
        "definition": _display_lines(entry.definition),
        "translation": _display_lines(entry.translation),
        "posText": _part_of_speech(entry.pos),
        "tagLabels": [TAG_LABELS[tag] for tag in tags],
        "frequencyText": _frequency_text(entry),
        "exchangeText": _exchange_text(entry.exchange),
    }


def _display_lines(value: str) -> str:
    return value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")


def _part_of_speech(value: str) -> str:
    parts: list[str] = []
    for item in value.split("/"):
        label = item.split(":", 1)[0].strip()
        if label and label not in parts:
            parts.append(label)
    return " · ".join(parts)


def _frequency_text(entry: DictionaryEntry) -> str:
    parts: list[str] = []
    if entry.frq > 0:
        parts.append(f"现代词频 #{entry.frq}")
    if entry.bnc > 0:
        parts.append(f"BNC #{entry.bnc}")
    return " · ".join(parts)


def _exchange_text(value: str) -> str:
    parts: list[str] = []
    for item in value.split("/"):
        key, separator, word = item.partition(":")
        if separator and word and key in EXCHANGE_LABELS:
            parts.append(f"{EXCHANGE_LABELS[key]} {word}")
    return " · ".join(parts)
