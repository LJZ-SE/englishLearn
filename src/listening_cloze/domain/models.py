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


class SceneKey(str):
    @property
    def value(self) -> str:
        """兼容旧枚举调用，同时保持新场景 key 的字符串语义。"""
        return str(self)


@dataclass(frozen=True, slots=True)
class SceneSelection:
    top_scene: str | None
    sub_scene: str | None = None

    def __post_init__(self) -> None:
        if self.top_scene is not None and not self.top_scene:
            raise ValueError("大类不能为空字符串")
        if self.sub_scene is not None and not self.sub_scene:
            raise ValueError("子场景不能为空字符串")
        if self.sub_scene is not None and self.top_scene is None:
            raise ValueError("指定子场景时必须同时指定大类")
        if self.sub_scene is not None and not self.sub_scene.startswith(
            f"{self.top_scene}_"
        ):
            raise ValueError("子场景不能脱离所属大类")


@dataclass(frozen=True, slots=True, init=False)
class Question:
    id: str
    source_sentence_id: str
    sentence: str
    top_scene: str
    sub_scene: str | None
    difficulty: Difficulty
    canonical_answer: str
    equivalent_answers: tuple[str, ...]
    translation_zh: str

    def __init__(
        self,
        id: str,
        source_sentence_id: str,
        sentence: str,
        category: Category | str | None = None,
        difficulty: Difficulty | None = None,
        canonical_answer: str = "",
        equivalent_answers: tuple[str, ...] = (),
        translation_zh: str = "",
        *,
        top_scene: str | None = None,
        sub_scene: str | None = None,
    ) -> None:
        legacy_scene = category.value if isinstance(category, Category) else category
        if top_scene is not None and legacy_scene is not None and top_scene != legacy_scene:
            raise ValueError("大类与旧分类不一致")
        resolved_top_scene = top_scene or legacy_scene
        if not resolved_top_scene:
            raise ValueError("题目大类不能为空")
        if difficulty is None:
            raise ValueError("题目难度不能为空")

        object.__setattr__(self, "id", id)
        object.__setattr__(self, "source_sentence_id", source_sentence_id)
        object.__setattr__(self, "sentence", sentence)
        object.__setattr__(self, "top_scene", resolved_top_scene)
        object.__setattr__(self, "sub_scene", sub_scene)
        object.__setattr__(self, "difficulty", difficulty)
        object.__setattr__(self, "canonical_answer", canonical_answer)
        object.__setattr__(self, "equivalent_answers", equivalent_answers)
        object.__setattr__(self, "translation_zh", translation_zh)
        self.__post_init__()

    def __post_init__(self) -> None:
        if not self.canonical_answer.strip():
            raise ValueError("规范答案不能为空")

    @property
    def category(self) -> Category | SceneKey:
        """为旧调用保留只读分类视图，新代码使用 top_scene。"""
        try:
            return Category(self.top_scene)
        except ValueError:
            return SceneKey(self.top_scene)

    @property
    def blank_count(self) -> int:
        return len(self.canonical_answer.split())
