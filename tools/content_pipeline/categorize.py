from __future__ import annotations

import re

from tools.content_pipeline.models import CollectedSentence

CATEGORIES = ("daily", "exam", "movies", "news_podcasts")

_KEYWORDS = {
    "daily": {
        "breakfast",
        "bus",
        "cupboard",
        "dinner",
        "dishes",
        "home",
        "kitchen",
        "laundry",
        "please",
        "shopping",
        "train",
        "weekend",
    },
    "exam": {
        "academic",
        "analysis",
        "analyze",
        "assignment",
        "conclusion",
        "essay",
        "evidence",
        "exam",
        "examination",
        "grammar",
        "homework",
        "hypothesis",
        "lecture",
        "lesson",
        "paragraph",
        "professor",
        "research",
        "student",
        "study",
        "textbook",
        "theory",
        "university",
        "vocabulary",
    },
    "movies": {
        "actor",
        "actress",
        "cinema",
        "documentary",
        "director",
        "episode",
        "film",
        "movie",
        "script",
        "subtitles",
        "television",
        "theater",
    },
    "news_podcasts": {
        "announcement",
        "bank",
        "broadcast",
        "central",
        "economic",
        "economy",
        "government",
        "interview",
        "journalist",
        "market",
        "minister",
        "newspaper",
        "official",
        "police",
        "podcast",
        "president",
        "report",
        "stocks",
        "tv",
        "vote",
    },
}


class CategoryClassifier:
    def classify(self, item: CollectedSentence) -> str:
        if item.category_hint in CATEGORIES:
            return item.category_hint
        if item.source_author == "Source_VOA":
            return "news_podcasts"
        raw_words = set(re.findall(r"[a-z]+", item.text.casefold()))
        words = set(raw_words)
        for word in raw_words:
            if word.endswith("ies") and len(word) > 4:
                words.add(f"{word[:-3]}y")
            elif word.endswith("s") and len(word) > 3:
                words.add(word[:-1])
        scores = {category: len(words & keywords) for category, keywords in _KEYWORDS.items()}
        # 相同得分时使用固定类别顺序，保证题库构建可复现。
        return max(CATEGORIES, key=lambda category: (scores[category], -CATEGORIES.index(category)))
