from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from listening_cloze.infrastructure.audio_cache import AudioCache, AudioProfile


class TtsBackend(Protocol):
    def synthesize_to_file(self, text: str, target: Path, *, speed: float) -> float: ...


@dataclass(frozen=True, slots=True)
class PrefetchItem:
    question_id: str
    sentence: str
    playback_rate: float = 1.0


@dataclass(slots=True)
class _Task:
    key: str
    sentence: str
    profile: AudioProfile
    priority: int
    order: int
    lane: str
    notifications: list[_Notification] = field(default_factory=list)


ReadyCallback = Callable[[PrefetchItem, Path], None]
ErrorCallback = Callable[[PrefetchItem, Exception], None]


@dataclass(frozen=True, slots=True)
class _Notification:
    item: PrefetchItem
    on_ready: ReadyCallback
    on_error: ErrorCallback


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
        self._schedule(
            items[:3],
            lane="practice",
            priority_offset=0,
            replace_practice=True,
            on_ready=self._on_ready,
            on_error=self._on_error,
        )

    def schedule_background(
        self,
        items: Sequence[PrefetchItem],
        *,
        on_ready: ReadyCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        """追加低优先级任务，不打断或替换当前练习题的预生成队列。"""
        self._schedule(
            items,
            lane="background",
            priority_offset=100,
            replace_practice=False,
            on_ready=on_ready or (lambda _item, _path: None),
            on_error=on_error or (lambda _item, _error: None),
        )

    def _schedule(
        self,
        items: Sequence[PrefetchItem],
        *,
        lane: str,
        priority_offset: int,
        replace_practice: bool,
        on_ready: ReadyCallback,
        on_error: ErrorCallback,
    ) -> None:
        ready_now: list[tuple[_Notification, Path]] = []
        window = list(items[:3])
        requested_keys = {
            self._cache.cache_key(item.sentence, self._profile_for(item)) for item in window
        }

        with self._condition:
            if replace_practice:
                self._pending = {
                    key: task
                    for key, task in self._pending.items()
                    if task.lane != "practice" or key in requested_keys
                }
            for priority, item in enumerate(window):
                notification = _Notification(item, on_ready, on_error)
                profile = self._profile_for(item)
                cached_path = self._cache.valid_path(item.sentence, profile)
                if cached_path is not None:
                    ready_now.append((notification, cached_path))
                    continue

                key = self._cache.cache_key(item.sentence, profile)
                task = self._inflight.get(key) or self._pending.get(key)
                task_priority = priority_offset + priority
                if task is None:
                    task = _Task(
                        key=key,
                        sentence=item.sentence,
                        profile=profile,
                        priority=task_priority,
                        order=self._next_order(),
                        lane=lane,
                    )
                    self._pending[key] = task
                else:
                    task.priority = min(task.priority, task_priority)
                    if lane == "practice":
                        task.lane = "practice"
                if not any(
                    current.item == item
                    and current.on_ready is on_ready
                    and current.on_error is on_error
                    for current in task.notifications
                ):
                    task.notifications.append(notification)
            self._condition.notify_all()

        for notification, path in ready_now:
            self._notify_ready(notification, path)

    def _profile_for(self, item: PrefetchItem) -> AudioProfile:
        return replace(self._profile, synthesis_speed=item.playback_rate)

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
        target = self._cache.path_for(task.sentence, task.profile)
        attempts = 2 if task.lane == "practice" and task.priority == 0 else 1
        last_error: Exception | None = None
        for _attempt in range(attempts):
            temporary = self._cache.temporary_path(target)
            temporary.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._backend.synthesize_to_file(
                    task.sentence,
                    temporary,
                    speed=task.profile.synthesis_speed,
                )
                self._cache.commit(temporary, target)
                for notification in tuple(task.notifications):
                    self._notify_ready(notification, target)
                return
            except Exception as error:
                temporary.unlink(missing_ok=True)
                last_error = error

        assert last_error is not None
        for notification in tuple(task.notifications):
            self._notify_error(notification, last_error)

    def _notify_ready(self, notification: _Notification, path: Path) -> None:
        try:
            notification.on_ready(notification.item, path)
        except Exception:
            return

    def _notify_error(self, notification: _Notification, error: Exception) -> None:
        try:
            notification.on_error(notification.item, error)
        except Exception:
            return
