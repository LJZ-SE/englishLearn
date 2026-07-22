import random
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class FeedbackKind(StrEnum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    LEVEL_UP = "level_up"
    LEVEL_DOWN = "level_down"


@dataclass(frozen=True, slots=True)
class FeedbackPool:
    texts: tuple[str, ...]
    animations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FeedbackChoice:
    text: str
    animation: str


DEFAULT_FEEDBACK_POOLS: Mapping[FeedbackKind, FeedbackPool] = {
    FeedbackKind.CORRECT: FeedbackPool(
        texts=(
            "太棒了，听得很准！",
            "完全正确！",
            "这句听懂了！",
            "漂亮，继续保持！",
            "你的耳朵很敏锐！",
        ),
        animations=("bounce_wave", "clap", "spin", "stretch_wave", "confetti"),
    ),
    FeedbackKind.INCORRECT: FeedbackPool(
        texts=(
            "别灰心，再听一次！",
            "差一点，再试试！",
            "放慢语速听听看。",
            "注意句子的连接发音。",
            "没关系，再挑战一次！",
        ),
        animations=("droop", "shake_head", "shrink_wave", "crouch", "sway"),
    ),
    FeedbackKind.LEVEL_UP: FeedbackPool(
        texts=("连续答对，难度升级！", "状态真好，迎接新挑战！"),
        animations=("level_up_rise", "level_up_sparkle"),
    ),
    FeedbackKind.LEVEL_DOWN: FeedbackPool(
        texts=("先放慢节奏，稳住再来！", "调整一下难度，继续积累！"),
        animations=("level_down_soft", "level_down_breathe"),
    ),
}


class FeedbackSelector:
    def __init__(
        self,
        pools: Mapping[FeedbackKind, FeedbackPool] = DEFAULT_FEEDBACK_POOLS,
        *,
        rng: random.Random | None = None,
    ) -> None:
        self._pools = dict(pools)
        self._rng = rng or random.Random()
        self._last_text: str | None = None
        self._last_animation: str | None = None
        for pool in self._pools.values():
            if len(pool.texts) < 2 or len(pool.animations) < 2:
                raise ValueError("反馈文案和动画池各自至少需要两个选项")

    def next(self, kind: FeedbackKind) -> FeedbackChoice:
        pool = self._pools[kind]
        available_texts = [text for text in pool.texts if text != self._last_text]
        available_animations = [
            animation for animation in pool.animations if animation != self._last_animation
        ]
        choice = FeedbackChoice(
            text=self._rng.choice(available_texts),
            animation=self._rng.choice(available_animations),
        )
        self._last_text = choice.text
        self._last_animation = choice.animation
        return choice
