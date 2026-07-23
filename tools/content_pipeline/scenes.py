from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SceneDefinition:
    top_key: str
    top_label: str
    key: str
    label: str
    quota: int


SCENES = (
    SceneDefinition("daily", "日常生活", "daily_home", "家庭家务", 1500),
    SceneDefinition("daily", "日常生活", "daily_social", "社交沟通", 1800),
    SceneDefinition("daily", "日常生活", "daily_shopping", "购物服务", 1400),
    SceneDefinition("daily", "日常生活", "daily_food", "餐饮烹饪", 1300),
    SceneDefinition("travel", "出行旅行", "travel_transport", "交通通勤", 1200),
    SceneDefinition("travel", "出行旅行", "travel_directions", "问路导航", 900),
    SceneDefinition("travel", "出行旅行", "travel_hotel", "酒店住宿", 1100),
    SceneDefinition("travel", "出行旅行", "travel_tourism", "旅行观光", 1300),
    SceneDefinition("work", "职场商务", "work_office", "办公协作", 1300),
    SceneDefinition("work", "职场商务", "work_meetings", "会议演示", 1100),
    SceneDefinition("work", "职场商务", "work_contact", "邮件电话", 1000),
    SceneDefinition("work", "职场商务", "work_jobs", "求职面试", 1100),
    SceneDefinition("study", "学习考试", "study_campus", "校园课堂", 1100),
    SceneDefinition("study", "学习考试", "study_exams", "考试备考", 900),
    SceneDefinition("study", "学习考试", "study_academic", "学术研究", 1000),
    SceneDefinition("study", "学习考试", "study_language", "语言学习", 1000),
    SceneDefinition("health", "健康医疗", "health_clinic", "医院就诊", 800),
    SceneDefinition("health", "健康医疗", "health_pharmacy", "药店用药", 600),
    SceneDefinition("health", "健康医疗", "health_fitness", "健身运动", 800),
    SceneDefinition("health", "健康医疗", "health_wellbeing", "身心健康", 800),
    SceneDefinition("technology", "科技科学", "technology_devices", "数码设备", 800),
    SceneDefinition("technology", "科技科学", "technology_software", "互联网软件", 800),
    SceneDefinition("technology", "科技科学", "technology_engineering", "工程技术", 700),
    SceneDefinition("technology", "科技科学", "technology_science", "科学科普", 700),
    SceneDefinition("culture", "文化娱乐", "culture_movies", "影视戏剧", 800),
    SceneDefinition("culture", "文化娱乐", "culture_music", "音乐艺术", 700),
    SceneDefinition("culture", "文化娱乐", "culture_books", "阅读文学", 700),
    SceneDefinition("culture", "文化娱乐", "culture_sports", "体育休闲", 800),
    SceneDefinition("news", "新闻社会", "news_current", "时事新闻", 600),
    SceneDefinition("news", "新闻社会", "news_business", "财经商业", 500),
    SceneDefinition("news", "新闻社会", "news_public", "法律公共事务", 400),
    SceneDefinition("news", "新闻社会", "news_environment", "环境社会", 500),
    SceneDefinition("cet", "四六级考试", "cet_cet4", "四级 CET-4", 3000),
    SceneDefinition("cet", "四六级考试", "cet_cet6", "六级 CET-6", 3000),
)

TOP_SCENES = tuple(dict.fromkeys((scene.top_key, scene.top_label) for scene in SCENES))
SUB_SCENES = {scene.key: scene for scene in SCENES}
TOTAL_SENTENCE_QUOTA = sum(scene.quota for scene in SCENES)


def scene_by_key(key: str) -> SceneDefinition:
    return SUB_SCENES[key]
