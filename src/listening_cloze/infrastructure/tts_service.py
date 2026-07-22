from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from listening_cloze.infrastructure.audio_cache import AudioCache, AudioProfile


class TtsBackend(Protocol):
    def synthesize_to_file(self, text: str, target: Path) -> float: ...


@dataclass(frozen=True, slots=True)
class PrefetchItem:
    question_id: str
    sentence: str


@dataclass(slots=True)
class _Task:
    key: str
    sentence: str
    priority: int
    order: int
    items: list[PrefetchItem] = field(default_factory=list)


ReadyCallback = Callable[[PrefetchItem, Path], None]
ErrorCallback = Callable[[PrefetchItem, Exception], None]


class TtsPrefetchService:
    def __init__(
        self,
        backend: TtsBackend,
        cache: AudioCache,
        profile: AudioProfile,
        *,
        on_ready: ReadyCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self._backend = backend
        self._cache = cache
        self._profile = profile
        self._on_ready = on_ready or (lambda _item, _path: None)
        self._on_error = on_error or (lambda _item, _error: None)
        self._condition = threading.Condition()
        self._pending: dict[str, _Task] = {}
        self._inflight: dict[str, _Task] = {}
        self._stopping = False
        self._thread: threading.Thread | None = None
        self._order = 0

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping = False
            self._thread = threading.Thread(
                target=self._run,
                name="listening-cloze-tts",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._condition:
            self._stopping = True
            self._pending.clear()
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def schedule(self, items: Sequence[PrefetchItem]) -> None:
        ready_now: list[tuple[PrefetchItem, Path]] = []
        window = list(items[:3])
        requested_keys = {self._cache.cache_key(item.sentence, self._profile) for item in window}

        with self._condition:
            self._pending = {
                key: task for key, task in self._pending.items() if key in requested_keys
            }
            for priority, item in enumerate(window):
                cached_path = self._cache.valid_path(item.sentence, self._profile)
                if cached_path is not None:
                    ready_now.append((item, cached_path))
                    continue

                key = self._cache.cache_key(item.sentence, self._profile)
                task = self._inflight.get(key) or self._pending.get(key)
                if task is None:
                    task = _Task(
                        key=key,
                        sentence=item.sentence,
                        priority=priority,
                        order=self._next_order(),
                    )
                    self._pending[key] = task
                else:
                    task.priority = min(task.priority, priority)
                if item not in task.items:
                    task.items.append(item)
            self._condition.notify_all()

        for item, path in ready_now:
            self._notify_ready(item, path)

    def _next_order(self) -> int:
        self._order += 1
        return self._order

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._stopping or bool(self._pending))
                if self._stopping:
                    return
                task = min(
                    self._pending.values(),
                    key=lambda candidate: (candidate.priority, candidate.order),
                )
                self._pending.pop(task.key, None)
                self._inflight[task.key] = task

            self._execute(task)

            with self._condition:
                self._inflight.pop(task.key, None)

    def _execute(self, task: _Task) -> None:
        target = self._cache.path_for(task.sentence, self._profile)
        attempts = 2 if task.priority == 0 else 1
        last_error: Exception | None = None
        for _attempt in range(attempts):
            temporary = self._cache.temporary_path(target)
            temporary.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._backend.synthesize_to_file(task.sentence, temporary)
                self._cache.commit(temporary, target)
                for item in tuple(task.items):
                    self._notify_ready(item, target)
                return
            except Exception as error:
                temporary.unlink(missing_ok=True)
                last_error = error

        assert last_error is not None
        for item in tuple(task.items):
            self._notify_error(item, last_error)

    def _notify_ready(self, item: PrefetchItem, path: Path) -> None:
        try:
            self._on_ready(item, path)
        except Exception:
            return

    def _notify_error(self, item: PrefetchItem, error: Exception) -> None:
        try:
            self._on_error(item, error)
        except Exception:
            return
