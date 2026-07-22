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
    "daily_home": _scene_words(
        "home kitchen laundry dishes cupboard clean family house apartment bedroom "
        "bathroom door window floor mother father brother sister child children parent "
        "wife husband baby furniture wash towel key neighbor"
    ),
    "daily_social": _scene_words(
        "friend friends invite party neighbor welcome conversation together visit meet help "
        "sorry thank thanks please hello goodbye smile laugh talk tell ask answer love"
    ),
    "daily_shopping": _scene_words(
        "buy bought sell sold shop shopping price cost cashier refund size store market pay paid "
        "money dollar pound cheap expensive sale customer purchase bill card cash"
    ),
    "daily_food": _scene_words(
        "breakfast lunch dinner cook cooking restaurant menu meal food eat ate drink drank coffee "
        "tea bread meat fish chicken fruit vegetable hungry delicious plate cup bottle grill"
    ),
    "travel_transport": _scene_words(
        "train bus taxi airport flight station ticket commute platform car drive drove driver "
        "road bicycle bike subway railway ship boat traffic passenger journey depart arrive"
    ),
    "travel_directions": _scene_words(
        "direction directions turn map route locate street north south east west across behind "
        "front beside between corner straight address"
    ),
    "travel_hotel": _scene_words(
        "hotel motel hostel reserve reservation double guest desk stay stayed staying "
        "reception booking suite luggage accommodation key checkout"
    ),
    "travel_tourism": _scene_words(
        "tour travel vacation holiday journey museum landmark sightseeing tourist trip abroad "
        "beach mountain country city passport visa guide destination visit explore island summer "
        "weekend camp camping sight foreign adventure cruise"
    ),
    "work_office": _scene_words(
        "office colleague project deadline report document team task boss manager employee "
        "company client file schedule plan budget department contract business copy"
    ),
    "work_meetings": _scene_words(
        "meeting presentation agenda discuss conference slide attendees session chairman committee "
        "speech speaker audience proposal decision minutes topic debate workshop discussion gather "
        "gathered board negotiate negotiation seminar discussed presented attend attended"
    ),
    "work_contact": _scene_words(
        "email call phone message contact reply attachment send sent mail letter write wrote text "
        "telephone address response notify forward receive"
    ),
    "work_jobs": _scene_words(
        "job interview resume salary hire career applicant position employment employer worker "
        "profession application vacancy wage promotion retire qualification occupation staff "
        "earn income quit unemployed labor labour working worked fired hired employ workplace"
    ),
    "study_campus": _scene_words(
        "campus classroom lecture professor student university lesson school teacher class college "
        "pupil homework assignment course educate education graduate semester"
    ),
    "study_exams": _scene_words(
        "exam examination test quiz revise revision score question prepare study answer grade pass "
        "fail practice exercise result mark correct"
    ),
    "study_academic": _scene_words(
        "research hypothesis evidence analysis paper academic theory data method result conclusion "
        "experiment study science mathematical equation history scholar article theorem proof "
        "knowledge philosophy concept subject statistics survey calculate calculation"
    ),
    "study_language": _scene_words(
        "language grammar vocabulary pronunciation translate translation english word words speak "
        "sentence phrase meaning spell dictionary french german spanish chinese learn"
    ),
    "health_clinic": _scene_words(
        "doctor hospital clinic appointment patient symptom nurse medical sick ill disease pain "
        "fever health blood treatment surgery injury dentist emergency"
    ),
    "health_pharmacy": _scene_words(
        "medicine pharmacy prescription tablet dose drug pharmacist pill pills medication remedy "
        "vitamin antibiotic aspirin injection dosage capsule cure vaccine cream syrup poison "
        "chemist cough headache cold healing therapy ointment bandage"
    ),
    "health_fitness": _scene_words(
        "exercise gym fitness run running workout sport train training walk walking swim swimming "
        "race athlete muscle weight yoga physical cycling"
    ),
    "health_wellbeing": _scene_words(
        "sleep stress relax wellbeing mental healthy rest tired worry worried calm happy sad "
        "feeling "
        "feel anxiety dream comfortable peace habit"
    ),
    "technology_devices": _scene_words(
        "phone laptop screen device camera battery television radio recorder keyboard "
        "mouse printer cable machine digital video microphone hardware monitor speaker headphones "
        "headset smartphone tablet disk chip electronic tape clock button switch remote photograph "
        "picture electric memory"
    ),
    "technology_software": _scene_words(
        "software app internet website password account online program code file download upload "
        "network server browser database login web application algorithm webpage site link search "
        "click install update user virus programming developer google facebook twitter information "
        "portal cloud email cyber computer system desktop operating windows android ios"
    ),
    "technology_engineering": _scene_words(
        "engineer engineering machine design build technical technology equipment factory "
        "industry industrial construction structure material electrical mechanical engine motor "
        "bridge building architecture tool metal power wheel manufacture repair"
    ),
    "technology_science": _scene_words(
        "science scientist experiment space energy laboratory discovery planet earth moon star "
        "physics chemical biology atom universe scientific temperature molecule gravity solar "
        "species evolution gene astronomy"
    ),
    "culture_movies": _scene_words(
        "movie film cinema actor actress director episode theater theatre television show script "
        "scene screen comedy drama character watch"
    ),
    "culture_music": _scene_words(
        "music song concert singer instrument album orchestra piano guitar violin dance dancing "
        "band voice sing sang musical art"
    ),
    "culture_books": _scene_words(
        "book novel author read reading library literature story poem poetry writer chapter page "
        "publish newspaper magazine tale"
    ),
    "culture_sports": _scene_words(
        "sport sports game match team player football hobby leisure baseball basketball tennis "
        "golf coach club ball athlete tournament score"
    ),
    "news_current": _scene_words(
        "news report journalist announce announcement president minister current international "
        "official leader nation headline broadcast correspondent political politics crisis "
        "incident recent former national administration"
    ),
    "news_business": _scene_words(
        "business market bank economy economic stocks company finance financial trade price growth "
        "investment industry profit tax money dollar million percent rate increase decrease sales "
        "income fund budget debt revenue"
    ),
    "news_public": _scene_words(
        "law court police government council public election vote legal judge crime policy state "
        "parliament military authority community rights"
    ),
    "news_environment": _scene_words(
        "environment climate weather pollution wildlife flood nature rain storm snow fire forest "
        "animal animals river sea water earthquake temperature"
    ),
}

_SCENE_PHRASES = {
    "travel_directions": (
        "turn left",
        "turn right",
        "on your left",
        "on your right",
        "how do i get",
        "where is the",
        "which way",
    ),
    "travel_hotel": (
        "hotel room",
        "hotel and room",
        "stay at",
        "stay for",
        "one night",
        "two nights",
        "double and night",
        "check in",
        "check out",
    ),
    "technology_devices": ("phone and computer",),
    "work_office": (
        "at work",
        "my work",
        "your work",
        "work on the",
        "working on the",
    ),
}


@dataclass(frozen=True, slots=True)
class SceneClassification:
    top_scene: str | None
    sub_scene: str | None
    confidence: float
    method: str


class SceneClassifier:
    def scene_scores(self, text: str) -> dict[str, float]:
        words = _normalized_words(text)
        scores = {
            scene_key: float(len(words.intersection(keywords)))
            for scene_key, keywords in _SCENE_KEYWORDS.items()
        }
        normalized = text.casefold().replace("-", " ")
        for scene_key, phrases in _SCENE_PHRASES.items():
            scores[scene_key] += 2.0 * sum(phrase in normalized for phrase in phrases)
        return scores

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

        scores = self.scene_scores(text)
        ordered = sorted(scores, key=lambda key: (-scores[key], key))
        best, runner_up = ordered[:2]
        best_score = scores[best]
        margin = best_score - scores[runner_up]
        confidence = min(1.0, (best_score + margin) / 6.0)
        if best_score < 2.0 or margin < 0.75:
            return SceneClassification(None, None, confidence, "llm_required")
        scene = SUB_SCENES[best]
        return SceneClassification(scene.top_key, scene.key, confidence, "keyword")

    def classify_candidate(
        self,
        text: str,
        *,
        top_scene: str | None = None,
        sub_scene: str | None = None,
        protected: bool = False,
        source_name: str = "",
    ) -> SceneClassification:
        """对生产候选池采用单一关键词门槛，弱信号或冲突项保留可审计状态。"""
        explicit = self.classify(text, top_scene=top_scene, sub_scene=sub_scene)
        if explicit.method == "source_explicit":
            return explicit
        if protected:
            return SceneClassification(None, None, explicit.confidence, "llm_required")
        if explicit.method == "keyword":
            return explicit
        scores = self.scene_scores(text)
        best_score = max(scores.values())
        winners = sorted(key for key, score in scores.items() if score == best_score)
        if best_score >= 1.0 and len(winners) == 1:
            scene = SUB_SCENES[winners[0]]
            return SceneClassification(
                scene.top_key,
                scene.key,
                min(0.95, 0.35 + best_score * 0.15),
                "candidate_keyword",
            )
        if source_name == "English Wikinews":
            scene = SUB_SCENES["news_current"]
            return SceneClassification(
                scene.top_key,
                scene.key,
                0.45,
                "candidate_source",
            )
        return SceneClassification(None, None, explicit.confidence, "out_of_candidate_pool")


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
