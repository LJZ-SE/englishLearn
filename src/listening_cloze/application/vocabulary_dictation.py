from __future__ import annotations

import random
from dataclasses import dataclass

from listening_cloze.domain.vocabulary_dictation import (
    is_vocabulary_answer_correct,
)
from listening_cloze.infrastructure.database import UserRepository, VocabularyEntry
from listening_cloze.infrastructure.dictionary import DictionaryEntry, DictionaryRepository

SESSION_SETTING_KEY = "vocabulary_dictation_session"
SOURCE_SETTING_KEY = "vocabulary_dictation_source"
COUNT_SETTING_KEY = "vocabulary_dictation_count"


@dataclass(slots=True)
class VocabularyDictationState:
    source: str
    selected_count: int | str
    entry_ids: list[str]
    position: int = 0
    hint_level: int = 0
    submitted: bool = False
    correct: bool = False
    outcome: str = ""
    results: list[dict[str, object]] | None = None

    def __post_init__(self) -> None:
        if self.results is None:
            self.results = []


class VocabularyDictationService:
    """维护独立于句子填空的词条听写会话。"""

    def __init__(
        self,
        users: UserRepository,
        dictionary: DictionaryRepository,
        *,
        rng: random.Random | None = None,
    ) -> None:
        self._users = users
        self._dictionary = dictionary
        self._rng = rng or random.Random()
        self._state: VocabularyDictationState | None = None
        self._entries: list[VocabularyEntry] = []
        self._dictionary_cache: dict[str, dict[str, object]] = {}

    @property
    def active(self) -> bool:
        return self._state is not None and bool(self._entries)

    @property
    def current_entry(self) -> VocabularyEntry:
        if not self.active or self._state is None:
            raise RuntimeError("词汇听写尚未开始")
        return self._entries[self._state.position]

    @property
    def current_audio_id(self) -> str:
        return f"vocabulary:{self.current_entry.entry_id}"

    @property
    def current_term(self) -> str:
        return self.current_entry.term

    @property
    def prefetch_entries(self) -> tuple[VocabularyEntry, ...]:
        if not self.active or self._state is None:
            return ()
        return tuple(self._entries[self._state.position : self._state.position + 3])

    def config_view(self) -> dict[str, object]:
        counts = self._users.vocabulary_dictation_counts()
        raw_source = str(self._users.get_setting(SOURCE_SETTING_KEY, "new"))
        source = raw_source if raw_source in {"new", "mastered"} else "new"
        raw_count = self._users.get_setting(COUNT_SETTING_KEY, 10)
        selected_count: int | str = (
            raw_count
            if isinstance(raw_count, (int, str))
            and not isinstance(raw_count, bool)
            and raw_count in {10, 20, 30, "all"}
            else 10
        )
        saved = self._load_saved_state()
        remaining = 0
        if saved is not None:
            remaining = max(0, len(saved.entry_ids) - saved.position)
        return {
            "page": "config",
            "source": source,
            "selectedCount": selected_count,
            "newCount": counts["pending"],
            "masteredCount": counts["mastered"],
            "resumeAvailable": saved is not None and remaining > 0,
            "resumeRemaining": remaining,
        }

    def start(self, *, source: str, count: int | str) -> None:
        normalized_source = self._normalize_source(source)
        entries = self._users.select_vocabulary_dictation_entries(
            source=normalized_source,
            count=count,
            rng=self._rng,
        )
        if not entries:
            raise RuntimeError("当前筛选条件下没有可听写的词汇")
        visible_source = "mastered" if normalized_source == "mastered" else "new"
        self._users.set_setting(SOURCE_SETTING_KEY, visible_source)
        self._users.set_setting(COUNT_SETTING_KEY, count)
        self._entries = entries
        self._state = VocabularyDictationState(
            source=visible_source,
            selected_count=count,
            entry_ids=[entry.entry_id for entry in entries],
        )
        self._save_state()

    def resume(self) -> bool:
        state = self._load_saved_state()
        if state is None:
            return False
        entries = self._users.get_vocabulary_entries(state.entry_ids)
        if [entry.entry_id for entry in entries] != state.entry_ids:
            self._users.set_setting(SESSION_SETTING_KEY, None)
            return False
        self._state = state
        self._entries = entries
        return True

    def request_hint(self, level: int) -> None:
        state = self._require_state()
        if state.submitted:
            return
        if level not in {1, 2, 3, 4}:
            raise ValueError("提示级别只支持 1 到 4")
        if level > state.hint_level + 1:
            raise ValueError("提示必须按顺序逐级查看")
        state.hint_level = max(state.hint_level, level)
        if level == 4:
            self._record_outcome("revealed", correct=False)
        else:
            self._save_state()

    def submit(self, answer: str) -> None:
        state = self._require_state()
        if state.submitted:
            return
        if not answer.strip():
            raise ValueError("请先填写听到的单词或短语")
        correct = is_vocabulary_answer_correct(
            expected=self.current_entry.term,
            submitted=answer,
        )
        if correct:
            outcome = (
                "independent_correct"
                if state.hint_level <= 1
                else "hint_correct"
            )
        else:
            outcome = "wrong"
        self._record_outcome(outcome, correct=correct)

    def next_item(self) -> bool:
        state = self._require_state()
        if not state.submitted:
            raise RuntimeError("请先提交本题")
        if state.position + 1 >= len(self._entries):
            self._users.set_setting(SESSION_SETTING_KEY, None)
            return False
        state.position += 1
        state.hint_level = 0
        state.submitted = False
        state.correct = False
        state.outcome = ""
        self._save_state()
        return True

    def finish(self) -> None:
        self._users.set_setting(SESSION_SETTING_KEY, None)

    def view(self, *, page: str) -> dict[str, object]:
        if not self.active or self._state is None:
            return self.config_view()
        state = self._state
        entry = self.current_entry
        dictionary = self._dictionary_payload(entry.term)
        counts = self._users.vocabulary_dictation_counts()
        visible_term = entry.term if state.submitted or state.hint_level >= 4 else ""
        result_rows = list(state.results or [])
        independent_count = sum(
            row.get("rawOutcome") == "independent_correct" for row in result_rows
        )
        hint_count = sum(
            row.get("rawOutcome") == "hint_correct" for row in result_rows
        )
        wrong_count = sum(
            row.get("rawOutcome") in {"wrong", "revealed"} for row in result_rows
        )
        return {
            "page": page,
            "source": state.source,
            "selectedCount": state.selected_count,
            "newCount": counts["pending"],
            "masteredCount": counts["mastered"],
            "resumeAvailable": False,
            "resumeRemaining": max(0, len(self._entries) - state.position),
            "index": state.position,
            "total": len(self._entries),
            "audioState": "ready",
            "autoPlayPass": 0,
            "hintLevel": state.hint_level,
            "hintDefinition": (
                dictionary["hintDefinition"] if state.hint_level >= 2 else ""
            ),
            "hintInitials": (
                _initial_and_length(entry.term) if state.hint_level >= 3 else ""
            ),
            "homophoneMeaning": dictionary["homophoneMeaning"],
            "submitted": state.submitted,
            "correct": state.correct,
            "outcome": _qml_outcome(state.outcome),
            "term": visible_term,
            "phonetic": dictionary["phonetic"] if state.submitted else "",
            "partOfSpeech": dictionary["partOfSpeech"] if state.submitted else "",
            "chineseDefinitions": (
                dictionary["chineseDefinitions"] if state.submitted else []
            ),
            "englishDefinitions": (
                dictionary["englishDefinitions"] if state.submitted else []
            ),
            "inflections": dictionary["inflections"] if state.submitted else "",
            "streak": entry.independent_correct_streak,
            "mastered": entry.mastered_at is not None,
            "newlyMastered": bool(
                result_rows and result_rows[-1].get("newlyMastered")
                and result_rows[-1].get("entryId") == entry.entry_id
            ),
            "remainingToMaster": max(0, 5 - entry.independent_correct_streak),
            "results": result_rows,
            "independentCorrectCount": independent_count,
            "hintCorrectCount": hint_count,
            "wrongCount": wrong_count,
            "newlyMasteredCount": sum(
                bool(row.get("newlyMastered")) for row in result_rows
            ),
            "pendingCount": counts["pending"],
            "progress": self._progress_states(page, result_rows),
        }

    def _progress_states(
        self,
        page: str,
        result_rows: list[dict[str, object]],
    ) -> list[str]:
        progress = [str(row.get("outcome", "pending")) for row in result_rows]
        if page == "practice" and len(progress) < len(self._entries):
            progress.append("current")
        progress.extend(["pending"] * max(0, len(self._entries) - len(progress)))
        return progress

    def _record_outcome(self, outcome: str, *, correct: bool) -> None:
        state = self._require_state()
        before = self.current_entry
        updated = self._users.record_vocabulary_dictation_outcome(
            before.entry_id,
            outcome=outcome,
        )
        self._entries[state.position] = updated
        newly_mastered = before.mastered_at is None and updated.mastered_at is not None
        state.submitted = True
        state.correct = correct
        state.outcome = outcome
        assert state.results is not None
        state.results.append(
            {
                "entryId": updated.entry_id,
                "term": updated.term,
                "rawOutcome": outcome,
                "outcome": _qml_outcome(outcome),
                "streak": updated.independent_correct_streak,
                "mastered": updated.mastered_at is not None,
                "newlyMastered": newly_mastered,
            }
        )
        self._save_state()

    def _dictionary_payload(self, term: str) -> dict[str, object]:
        key = " ".join(term.casefold().split())
        cached = self._dictionary_cache.get(key)
        if cached is not None:
            return cached
        exact = tuple(
            entry
            for entry in self._dictionary.lookup(term)
            if " ".join(entry.word.casefold().split()) == key
        )
        first = exact[0] if exact else None
        chinese = _dictionary_lines(exact, "translation")
        english = _dictionary_lines(exact, "definition")
        homophones = self._dictionary.lookup_homophones(term, limit=1) if first else ()
        payload: dict[str, object] = {
            "phonetic": first.phonetic if first else "",
            "partOfSpeech": _part_of_speech(exact),
            "chineseDefinitions": chinese,
            "englishDefinitions": english,
            "inflections": _format_inflections(first.exchange) if first else "",
            "hintDefinition": "；".join(chinese[:2])
            or "；".join(english[:2])
            or "暂无词典释义",
            # 同音歧义只提前给目标词中文义，不暴露同音候选拼写，也不计提示。
            "homophoneMeaning": "；".join(chinese[:2]) if homophones else "",
        }
        self._dictionary_cache[key] = payload
        return payload

    def _save_state(self) -> None:
        state = self._require_state()
        self._users.set_setting(
            SESSION_SETTING_KEY,
            {
                "source": state.source,
                "selectedCount": state.selected_count,
                "entryIds": list(state.entry_ids),
                "position": state.position,
                "hintLevel": state.hint_level,
                "submitted": state.submitted,
                "correct": state.correct,
                "outcome": state.outcome,
                "results": list(state.results or []),
            },
        )

    def _load_saved_state(self) -> VocabularyDictationState | None:
        raw = self._users.get_setting(SESSION_SETTING_KEY)
        if not isinstance(raw, dict):
            return None
        entry_ids = [
            str(entry_id) for entry_id in raw.get("entryIds", []) if entry_id
        ]
        if not entry_ids:
            return None
        position = int(raw.get("position", 0))
        if position < 0 or position >= len(entry_ids):
            return None
        return VocabularyDictationState(
            source=str(raw.get("source") or "new"),
            selected_count=raw.get("selectedCount", 10),
            entry_ids=entry_ids,
            position=position,
            hint_level=int(raw.get("hintLevel", 0)),
            submitted=bool(raw.get("submitted", False)),
            correct=bool(raw.get("correct", False)),
            outcome=str(raw.get("outcome") or ""),
            results=[
                dict(item)
                for item in raw.get("results", [])
                if isinstance(item, dict)
            ],
        )

    def _require_state(self) -> VocabularyDictationState:
        if self._state is None:
            raise RuntimeError("词汇听写尚未开始")
        return self._state

    @staticmethod
    def _normalize_source(source: str) -> str:
        if source in {"new", "pending"}:
            return "pending"
        if source == "mastered":
            return "mastered"
        raise ValueError("词汇听写来源只支持生词或已掌握")


def _dictionary_lines(
    entries: tuple[DictionaryEntry, ...],
    attribute: str,
) -> list[str]:
    values: list[str] = []
    for entry in entries:
        raw = str(getattr(entry, attribute, ""))
        for line in raw.replace("\\n", "\n").splitlines():
            normalized = line.strip()
            if normalized and normalized not in values:
                values.append(normalized)
    return values


def _part_of_speech(entries: tuple[DictionaryEntry, ...]) -> str:
    values: list[str] = []
    for entry in entries:
        raw = entry.pos.split(":", maxsplit=1)[0].strip()
        if raw and raw not in values:
            values.append(raw)
    return " / ".join(values)


def _format_inflections(value: str) -> str:
    labels = {
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
    values: list[str] = []
    for item in value.split("/"):
        key, separator, word = item.partition(":")
        if separator and word and key in labels:
            values.append(f"{labels[key]} {word}")
    return " · ".join(values)


def _initial_and_length(term: str) -> str:
    hints: list[str] = []
    for word in term.split():
        letters = [character for character in word if character.isalnum()]
        if not letters:
            hints.append(word)
            continue
        hints.append(letters[0] + "_" * max(0, len(letters) - 1))
    return " ".join(hints)


def _qml_outcome(outcome: str) -> str:
    if outcome == "independent_correct":
        return "correct"
    if outcome == "hint_correct":
        return "hint"
    if outcome in {"wrong", "revealed"}:
        return "wrong"
    return ""
