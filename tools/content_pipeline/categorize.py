from __future__ import annotations

import re
from dataclasses import dataclass

from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import SUB_SCENES

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


def _scene_words(value: str) -> frozenset[str]:
    return frozenset(value.split())


_SCENE_KEYWORDS = {
    "daily_home": _scene_words("home kitchen laundry dishes cupboard clean family room house"),
    "daily_social": _scene_words(
        "friend invite party neighbor welcome conversation together visit"
    ),
    "daily_shopping": _scene_words("buy shop shopping price cost cashier refund size store"),
    "daily_food": _scene_words("breakfast lunch dinner cook cooking restaurant menu meal food"),
    "travel_transport": _scene_words(
        "train bus taxi airport flight station ticket commute platform"
    ),
    "travel_directions": _scene_words("direction turn left right map route locate near street"),
    "travel_hotel": _scene_words(
        "hotel room reserve reservation double night nights check-in stay"
    ),
    "travel_tourism": _scene_words(
        "tour travel vacation journey museum landmark sightseeing tourist"
    ),
    "work_office": _scene_words("office colleague project deadline report document team task"),
    "work_meetings": _scene_words("meeting presentation agenda discuss conference slide attendees"),
    "work_contact": _scene_words("email call phone message contact reply attachment send"),
    "work_jobs": _scene_words("job interview resume salary hire career applicant position"),
    "study_campus": _scene_words("campus classroom lecture professor student university lesson"),
    "study_exams": _scene_words("exam test revise revision score question prepare study"),
    "study_academic": _scene_words("research hypothesis evidence analysis paper academic theory"),
    "study_language": _scene_words(
        "language grammar vocabulary pronunciation translate english word"
    ),
    "health_clinic": _scene_words("doctor hospital clinic appointment patient symptom nurse"),
    "health_pharmacy": _scene_words("medicine pharmacy prescription tablet dose drug pharmacist"),
    "health_fitness": _scene_words("exercise gym fitness run running workout sport train"),
    "health_wellbeing": _scene_words("sleep stress relax wellbeing mental healthy rest"),
    "technology_devices": _scene_words("phone computer laptop screen device camera battery"),
    "technology_software": _scene_words("software app internet website password account online"),
    "technology_engineering": _scene_words(
        "engineer engineering machine system design build technical"
    ),
    "technology_science": _scene_words(
        "science scientist experiment space energy laboratory discovery"
    ),
    "culture_movies": _scene_words("movie film cinema actor actress director episode theater"),
    "culture_music": _scene_words("music song concert singer instrument album orchestra"),
    "culture_books": _scene_words("book novel author read reading library literature story"),
    "culture_sports": _scene_words("sport game match team player football hobby leisure"),
    "news_current": _scene_words("news report journalist announce president minister current"),
    "news_business": _scene_words("business market bank economy economic stocks company finance"),
    "news_public": _scene_words("law court police government council public election vote"),
    "news_environment": _scene_words("environment climate weather pollution wildlife flood nature"),
}


@dataclass(frozen=True, slots=True)
class SceneClassification:
    top_scene: str | None
    sub_scene: str | None
    confidence: float
    method: str


class SceneClassifier:
    def classify(
        self,
        value: str | CollectedSentence,
        *,
        top_scene: str | None = None,
        sub_scene: str | None = None,
    ) -> SceneClassification:
        if isinstance(value, CollectedSentence):
            text = value.text
            top_scene = top_scene or value.top_scene
            sub_scene = sub_scene or value.sub_scene
        else:
            text = value
        explicit_scene = SUB_SCENES.get(sub_scene or "")
        if explicit_scene is not None and top_scene in (None, explicit_scene.top_key):
            return SceneClassification(
                top_scene=explicit_scene.top_key,
                sub_scene=explicit_scene.key,
                confidence=1.0,
                method="source_explicit",
            )

        words = _normalized_words(text)
        scores = {
            scene_key: float(len(words.intersection(keywords)))
            for scene_key, keywords in _SCENE_KEYWORDS.items()
        }
        ordered = sorted(scores, key=lambda key: (-scores[key], key))
        best, runner_up = ordered[:2]
        best_score = scores[best]
        margin = best_score - scores[runner_up]
        confidence = min(1.0, (best_score + margin) / 6.0)
        if best_score < 2.0 or margin < 0.75:
            return SceneClassification(None, None, confidence, "llm_required")
        scene = SUB_SCENES[best]
        return SceneClassification(scene.top_key, scene.key, confidence, "keyword")


def _normalized_words(text: str) -> set[str]:
    raw_words = set(re.findall(r"[a-z]+", text.casefold()))
    words = set(raw_words)
    for word in raw_words:
        if word.endswith("ies") and len(word) > 4:
            words.add(f"{word[:-3]}y")
        elif word.endswith("s") and len(word) > 3:
            words.add(word[:-1])
    return words


class CategoryClassifier:
    def classify(self, item: CollectedSentence) -> str:
        if item.category_hint in CATEGORIES:
            return item.category_hint
        if item.source_author == "Source_VOA":
            return "news_podcasts"
        words = _normalized_words(item.text)
        scores = {category: len(words & keywords) for category, keywords in _KEYWORDS.items()}
        # 相同得分时使用固定类别顺序，保证题库构建可复现。
        return max(CATEGORIES, key=lambda category: (scores[category], -CATEGORIES.index(category)))
