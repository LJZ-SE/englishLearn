from dataclasses import dataclass
from enum import StrEnum


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

    def next(self) -> "Difficulty":
        levels = tuple(type(self))
        return levels[min(levels.index(self) + 1, len(levels) - 1)]

    def previous(self) -> "Difficulty":
        levels = tuple(type(self))
        return levels[max(levels.index(self) - 1, 0)]


class Category(StrEnum):
    DAILY = "daily"
    EXAM = "exam"
    MOVIES = "movies"
    NEWS_PODCASTS = "news_podcasts"


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    source_sentence_id: str
    sentence: str
    category: Category
    difficulty: Difficulty
    canonical_answer: str
    equivalent_answers: tuple[str, ...] = ()
    translation_zh: str = ""

    def __post_init__(self) -> None:
        if not self.canonical_answer.strip():
            raise ValueError("规范答案不能为空")

    @property
    def blank_count(self) -> int:
        return len(self.canonical_answer.split())
