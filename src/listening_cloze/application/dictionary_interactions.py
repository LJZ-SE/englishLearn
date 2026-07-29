from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from listening_cloze.infrastructure.database import VocabularyEntry
from listening_cloze.infrastructure.tts_service import (
    ErrorCallback,
    PrefetchItem,
    ReadyCallback,
)


class VocabularyStore(Protocol):
    def has_vocabulary(self, term: str) -> bool: ...

    def add_dictionary_vocabulary(self, *, term: str) -> VocabularyEntry: ...


class BackgroundTtsService(Protocol):
    def schedule_background(
        self,
        items: Sequence[PrefetchItem],
        *,
        on_ready: ReadyCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None: ...


class DictionaryInteractionService:
    """协调词典查询后的收藏和低优先级读音生成。"""

    def __init__(self, vocabulary: VocabularyStore) -> None:
        self._vocabulary = vocabulary
        self._tts: BackgroundTtsService | None = None

    def attach_tts(self, service: BackgroundTtsService) -> None:
        self._tts = service

    def is_saved(self, term: str) -> bool:
        return self._vocabulary.has_vocabulary(term)

    def add_to_vocabulary(self, term: str) -> VocabularyEntry:
        return self._vocabulary.add_dictionary_vocabulary(term=term)

    def prefetch_pronunciation(
        self,
        term: str,
        *,
        on_ready: ReadyCallback,
        on_error: ErrorCallback,
    ) -> None:
        display_term = " ".join(term.split())
        if not display_term:
            raise ValueError("词汇或短语不能为空")
        if self._tts is None:
            raise RuntimeError("离线语音服务尚未就绪")
        normalized_term = display_term.casefold()
        self._tts.schedule_background(
            [PrefetchItem(f"dictionary:{normalized_term}", display_term)],
            on_ready=on_ready,
            on_error=on_error,
        )
