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


def _canonical_word(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return f"{word[:-3]}y"
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word


def _scene_words(value: str) -> frozenset[str]:
    return frozenset(_canonical_word(word) for word in value.split())


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

# 单独出现即可提供可靠场景证据的领域词。未列入这里的普通多义词只能参与审计，
# 不能靠改名为低置信方法绕过候选池门槛。
_SCENE_STRONG_KEYWORDS = {
    "daily_home": _scene_words(
        "home kitchen laundry dishes cupboard house apartment bedroom bathroom mother "
        "father brother sister children parent wife husband baby furniture towel neighbor"
    ),
    "daily_social": _scene_words(
        "friend friends invite party welcome conversation together sorry thank thanks hello "
        "goodbye"
    ),
    "daily_shopping": _scene_words(
        "buy bought sell sold shop shopping price cashier refund store pay paid money dollar cheap "
        "expensive sale customer purchase bill card cash"
    ),
    "daily_food": _scene_words(
        "breakfast lunch dinner cook cooking restaurant menu meal food eat ate drink drank coffee "
        "tea bread meat fish chicken fruit vegetable hungry delicious grill"
    ),
    "travel_transport": _scene_words(
        "train bus taxi airport flight station ticket commute platform car driver road bicycle "
        "bike subway railway traffic passenger depart arrive"
    ),
    "travel_directions": _scene_words("direction directions map route street corner address"),
    "travel_hotel": _scene_words(
        "hotel motel hostel reserve reservation reception booking suite guest luggage "
        "accommodation checkout lodging inn"
    ),
    "travel_tourism": _scene_words(
        "tour travel vacation holiday journey museum landmark sightseeing tourist trip abroad "
        "beach passport visa guide destination explore camping foreign "
        "adventure cruise"
    ),
    "work_office": _scene_words(
        "office colleague project deadline team task boss manager employee client schedule budget "
        "department contract business"
    ),
    "work_meetings": _scene_words(
        "presentation agenda conference attendees session chairman committee speaker audience "
        "proposal debate workshop board negotiate negotiation seminar"
    ),
    "work_contact": _scene_words(
        "email phone message contact reply attachment mail telephone response notify forward"
    ),
    "work_jobs": _scene_words(
        "job interview resume salary hire career applicant position employment employer worker "
        "profession vacancy wage promotion retire qualification occupation unemployed labor "
        "labour workplace"
    ),
    "study_campus": _scene_words(
        "campus classroom lecture professor student university lesson school teacher college pupil "
        "homework course education semester"
    ),
    "study_exams": _scene_words("exam examination quiz revision grade"),
    "study_academic": _scene_words(
        "research hypothesis evidence analysis academic theory data method conclusion experiment "
        "science history knowledge philosophy mathematical equation scholar article theorem proof "
        "statistics survey calculate calculation"
    ),
    "study_language": _scene_words(
        "language grammar vocabulary pronunciation translate translation english sentence phrase "
        "spell dictionary french german spanish chinese"
    ),
    "health_clinic": _scene_words(
        "doctor hospital clinic appointment patient symptom nurse medical sick illness disease "
        "pain fever health blood treatment surgery injury dentist emergency"
    ),
    "health_pharmacy": _scene_words(
        "medicine pharmacy prescription tablet dose drug pharmacist pill pills medication remedy "
        "vitamin antibiotic aspirin injection dosage capsule cure vaccine syrup cough headache "
        "therapy ointment bandage"
    ),
    "health_fitness": _scene_words(
        "exercise gym fitness workout running walking sport training swim swimming race athlete "
        "muscle yoga cycling"
    ),
    "health_wellbeing": _scene_words(
        "sleep stress relax wellbeing mental healthy tired worry worried calm anxiety"
    ),
    "technology_devices": _scene_words(
        "phone laptop screen device camera battery television radio recorder keyboard printer "
        "cable digital video microphone hardware monitor speaker headphones headset smartphone "
        "tablet disk chip electronic mouse"
    ),
    "technology_software": _scene_words(
        "software app internet website password online program code download upload network server "
        "browser database login web algorithm webpage click install update virus programming "
        "developer google facebook twitter portal cloud computer android ios"
    ),
    "technology_engineering": _scene_words(
        "engineer engineering machine design technical technology equipment factory industry "
        "industrial construction structure material electrical mechanical engine motor bridge "
        "building architecture tool metal power wheel manufacture repair"
    ),
    "technology_science": _scene_words(
        "science scientist experiment space energy laboratory discovery planet earth moon star "
        "physics chemical biology atom universe scientific temperature molecule gravity solar "
        "species evolution gene astronomy"
    ),
    "culture_movies": _scene_words(
        "movie film cinema actor actress director episode theater theatre television script comedy "
        "drama"
    ),
    "culture_music": _scene_words(
        "music song concert singer instrument album orchestra piano guitar violin band sing sang "
        "musical dance dancing voice art"
    ),
    "culture_books": _scene_words(
        "book novel author library literature poem poetry writer chapter publish magazine tale"
    ),
    "culture_sports": _scene_words(
        "sport sports game match team player football hobby leisure baseball basketball tennis "
        "golf coach club ball athlete tournament score"
    ),
    "news_current": _scene_words(
        "journalist announcement president minister international official leader nation "
        "headline broadcast correspondent political politics crisis recent national administration"
    ),
    "news_business": _scene_words(
        "bank economy economic stocks finance financial trade growth investment industry "
        "profit tax sales income fund budget debt revenue"
    ),
    "news_public": _scene_words(
        "law court police government council election vote legal judge crime policy parliament "
        "military rights"
    ),
    "news_environment": _scene_words(
        "environment climate weather pollution wildlife flood nature rain storm snow forest "
        "earthquake"
    ),
}

_CONTEXT_EXCLUDED_KEYWORDS = _scene_words(
    "account answer button city cold correct country desk double east family fired front key "
    "letter mark market meeting minutes news night pass plan position practice question remote "
    "result run staff stay stayed staying straight switch system worked working"
)

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
        "spend the night",
        "spent the night",
        "for the night",
        "book a room",
        "booked a room",
        "reserve a room",
        "reserved a room",
        "single room",
        "double room",
        "guest room",
        "room number",
        "room key",
        "vacant room",
        "available room",
        "front desk",
        "room service",
        "check in",
        "check out",
    ),
    "work_meetings": (
        "the meeting",
        "a meeting",
        "our meeting",
        "your meeting",
        "meeting with",
        "meeting at",
        "meeting room",
        "staff meeting",
        "board meeting",
        "team meeting",
        "press conference",
        "meet to discuss",
        "met to discuss",
    ),
    "study_exams": (
        "take a test",
        "take the test",
        "taking a test",
        "pass the test",
        "pass the exam",
        "fail the test",
        "fail the exam",
        "study for",
        "studying for",
        "prepare for the test",
        "prepare for the exam",
        "test score",
        "exam result",
        "exam score",
        "test result",
        "answer the question",
    ),
    "health_pharmacy": (
        "bad cold",
        "common cold",
        "catch cold",
        "catch a cold",
        "have a cold",
        "take medicine",
    ),
    "health_fitness": (
        "go for a run",
        "go running",
        "go walking",
        "physical training",
        "weight training",
    ),
    "technology_devices": (
        "phone and computer",
        "cell phone",
        "mobile phone",
        "tape recorder",
        "take a picture",
        "take a photo",
        "digital camera",
    ),
    "technology_software": (
        "user account",
        "online account",
        "email account",
        "operating system",
        "computer system",
        "software system",
        "log in",
        "sign in",
        "web site",
        "social network",
    ),
    "work_contact": (
        "phone call",
        "give me a call",
        "call me",
        "send me",
        "send you",
        "write to",
        "wrote to",
        "reply to",
        "email me",
    ),
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
    def strong_signals(self, sub_scene: str) -> tuple[frozenset[str], tuple[str, ...]]:
        if sub_scene not in SUB_SCENES:
            raise ValueError(f"未知场景: {sub_scene}")
        return _SCENE_STRONG_KEYWORDS[sub_scene], _SCENE_PHRASES.get(sub_scene, ())

    def strong_signal_evidence(
        self, text: str, sub_scene: str
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        keywords, phrases = self.strong_signals(sub_scene)
        words = _normalized_words(text)
        tokens = _normalized_tokens(text)
        return (
            tuple(sorted(words.intersection(keywords))),
            tuple(phrase for phrase in phrases if _phrase_present(tokens, phrase)),
        )

    def scene_scores(self, text: str) -> dict[str, float]:
        words = _normalized_words(text)
        scores = {
            scene_key: 2.0 * len(words.intersection(keywords))
            for scene_key, keywords in _SCENE_STRONG_KEYWORDS.items()
        }
        tokens = _normalized_tokens(text)
        for scene_key, phrases in _SCENE_PHRASES.items():
            scores[scene_key] += 2.0 * sum(
                _phrase_present(tokens, phrase) for phrase in phrases
            )
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
        evidence = {
            scene_key: self.strong_signal_evidence(text, scene_key)
            for scene_key in SUB_SCENES
        }
        qualified = {
            scene_key
            for scene_key, (keywords, phrases) in evidence.items()
            if phrases or len(keywords) >= 2
        }
        ordered = sorted(scores, key=lambda key: (-scores[key], key))
        best, runner_up = ordered[:2]
        best_score = scores[best]
        margin = best_score - scores[runner_up]
        confidence = min(1.0, (best_score + margin) / 6.0)
        if best not in qualified or best_score < 2.0 or margin < 0.75:
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
        """只接受高精度领域词或短语，弱信号与冲突项保留可审计状态。"""
        explicit = self.classify(text, top_scene=top_scene, sub_scene=sub_scene)
        if explicit.method == "source_explicit":
            return explicit
        if protected:
            return SceneClassification(None, None, explicit.confidence, "llm_required")
        if explicit.method == "keyword":
            return explicit
        words = _normalized_words(text)
        context_scores = {
            scene_key: len(words.intersection(keywords - _CONTEXT_EXCLUDED_KEYWORDS))
            for scene_key, keywords in _SCENE_KEYWORDS.items()
        }
        ordered_context = sorted(
            context_scores, key=lambda key: (-context_scores[key], key)
        )
        context_scene, context_runner_up = ordered_context[:2]
        context_score = context_scores[context_scene]
        if context_score >= 2 and context_score > context_scores[context_runner_up]:
            scene = SUB_SCENES[context_scene]
            return SceneClassification(
                scene.top_key,
                scene.key,
                min(0.85, 0.5 + context_score * 0.05),
                "context_keywords",
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
    return set(_normalized_tokens(text))


def _normalized_tokens(text: str) -> tuple[str, ...]:
    return tuple(_canonical_word(word) for word in re.findall(r"[a-z]+", text.casefold()))


def _phrase_present(tokens: tuple[str, ...], phrase: str) -> bool:
    phrase_tokens = tuple(_canonical_word(word) for word in phrase.split())
    width = len(phrase_tokens)
    return any(tokens[index : index + width] == phrase_tokens for index in range(len(tokens)))


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
