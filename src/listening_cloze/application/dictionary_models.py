from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from listening_cloze.application.dictionary_interactions import (
    BackgroundTtsService,
    DictionaryInteractionService,
)
from listening_cloze.infrastructure.dictionary import DictionaryEntry
from listening_cloze.infrastructure.tts_service import PrefetchItem

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
    playbackRequested = Signal(str, str)
    _pronunciationReady = Signal(object, str)
    _pronunciationFailed = Signal(object, str)

    def __init__(
        self,
        repository: DictionaryDataSource,
        parent: QObject | None = None,
        *,
        interactions: DictionaryInteractionService | None = None,
    ) -> None:
        super().__init__(parent)
        self._repository = repository
        self._interactions = interactions
        self._visible = False
        self._query = ""
        self._entries: list[dict[str, object]] = []
        self._result_text = ""
        self._error_text = ""
        self._pronunciations: dict[str, dict[str, str]] = {}
        self._save_errors: dict[str, str] = {}
        self._play_when_ready: set[str] = set()
        self._pronunciationReady.connect(self._apply_pronunciation_ready)
        self._pronunciationFailed.connect(self._apply_pronunciation_error)

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
            self._entries = [self._entry_to_qml(entry) for entry in results]
            self._result_text = f"找到 {len(results)} 个词条" if results else "没有找到该词条"
            self._error_text = ""
            if results and self._interactions is not None:
                first_term = results[0].word
                first_state = self._pronunciation_state(first_term)
                if first_state["state"] in {"idle", "error"}:
                    self._prefetch_pronunciation(first_term)
        except (OSError, RuntimeError, sqlite3.Error) as error:
            self._entries = []
            self._result_text = "词典暂时无法使用"
            self._error_text = str(error)
        self.dataChanged.emit()

    def attachTts(self, service: BackgroundTtsService) -> None:
        if self._interactions is None:
            return
        self._interactions.attach_tts(service)
        if self._entries:
            first_term = str(self._entries[0]["word"])
            if self._pronunciation_state(first_term)["state"] in {"idle", "error"}:
                self._prefetch_pronunciation(first_term)
                self.dataChanged.emit()

    @Slot(str)
    def addToVocabulary(self, term: str) -> None:
        if self._interactions is None:
            return
        key = _term_key(term)
        try:
            self._interactions.add_to_vocabulary(term)
            self._save_errors.pop(key, None)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            self._save_errors[key] = str(error)
        self._refresh_entries()
        self.dataChanged.emit()

    @Slot(str)
    def playPronunciation(self, term: str) -> None:
        key = _term_key(term)
        state = self._pronunciation_state(term)
        source = state["source"]
        if source:
            state["state"] = "playing"
            self._refresh_entries()
            self.dataChanged.emit()
            self.playbackRequested.emit(term, source)
            return
        self._play_when_ready.add(key)
        self._prefetch_pronunciation(term)
        self.dataChanged.emit()

    @Slot(str, bool)
    def setPronunciationPlaying(self, term: str, playing: bool) -> None:
        state = self._pronunciation_state(term)
        if playing:
            state["state"] = "playing"
        elif state["state"] == "playing":
            state["state"] = "ready"
        self._refresh_entries()
        self.dataChanged.emit()

    def handlePronunciationReady(self, item: PrefetchItem, path: Path) -> None:
        self._pronunciationReady.emit(item, path.resolve().as_uri())

    def handlePronunciationError(self, item: PrefetchItem, error: Exception) -> None:
        self._pronunciationFailed.emit(item, str(error))

    @Slot()
    def close(self) -> None:
        self._visible = False
        self.dataChanged.emit()

    def _entry_to_qml(self, entry: DictionaryEntry) -> dict[str, object]:
        result = _entry_to_qml(entry)
        key = _term_key(entry.word)
        state = self._pronunciation_state(entry.word)
        result.update(
            {
                "isSaved": (
                    self._interactions.is_saved(entry.word)
                    if self._interactions is not None
                    else False
                ),
                "saveError": self._save_errors.get(key, ""),
                "pronunciationState": state["state"],
                "pronunciationSource": state["source"],
                "pronunciationError": state["error"],
            }
        )
        return result

    def _pronunciation_state(self, term: str) -> dict[str, str]:
        return self._pronunciations.setdefault(
            _term_key(term),
            {"state": "idle", "source": "", "error": ""},
        )

    def _prefetch_pronunciation(self, term: str) -> None:
        if self._interactions is None:
            return
        state = self._pronunciation_state(term)
        if state["state"] == "generating":
            return
        state.update(state="generating", error="")
        self._refresh_entries()
        try:
            self._interactions.prefetch_pronunciation(
                term,
                on_ready=self.handlePronunciationReady,
                on_error=self.handlePronunciationError,
            )
        except (OSError, RuntimeError, ValueError) as error:
            state.update(state="error", error=str(error))
            self._play_when_ready.discard(_term_key(term))
            self._refresh_entries()

    @Slot(object, str)
    def _apply_pronunciation_ready(self, item: PrefetchItem, source: str) -> None:
        term = item.sentence
        key = _term_key(term)
        state = self._pronunciation_state(term)
        state.update(state="ready", source=source, error="")
        should_play = key in self._play_when_ready
        self._play_when_ready.discard(key)
        if should_play:
            state["state"] = "playing"
        self._refresh_entries()
        self.dataChanged.emit()
        if should_play:
            self.playbackRequested.emit(term, source)

    @Slot(object, str)
    def _apply_pronunciation_error(self, item: PrefetchItem, message: str) -> None:
        term = item.sentence
        key = _term_key(term)
        state = self._pronunciation_state(term)
        state.update(state="error", source="", error=message)
        self._play_when_ready.discard(key)
        self._refresh_entries()
        self.dataChanged.emit()

    def _refresh_entries(self) -> None:
        for entry in self._entries:
            term = str(entry["word"])
            key = _term_key(term)
            state = self._pronunciation_state(term)
            entry.update(
                {
                    "isSaved": (
                        self._interactions.is_saved(term)
                        if self._interactions is not None
                        else False
                    ),
                    "saveError": self._save_errors.get(key, ""),
                    "pronunciationState": state["state"],
                    "pronunciationSource": state["source"],
                    "pronunciationError": state["error"],
                }
            )


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


def _term_key(term: str) -> str:
    return " ".join(term.split()).casefold()


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
