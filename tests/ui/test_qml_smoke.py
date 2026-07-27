import random
from dataclasses import replace

import pytest
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QMetaObject,
    QObject,
    QPoint,
    QPointF,
    Qt,
    QUrl,
)
from PySide6.QtGui import QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from listening_cloze.application.controller import PracticeController
from listening_cloze.application.learning_models import LearningCenterViewModel
from listening_cloze.application.learning_service import LearningCenterService
from listening_cloze.application.practice_engine import PracticeEngine
from listening_cloze.infrastructure.database import (
    ContentQuestion,
    SceneMetadata,
    UserRepository,
)
from listening_cloze.runtime import ui_path


class _FakeContentRepository:
    def __init__(
        self,
        questions: list[ContentQuestion],
        scene_catalog: list[SceneMetadata] | None = None,
    ) -> None:
        self._questions = questions
        self._scene_catalog = scene_catalog

    def sample_questions(
        self,
        *,
        top_scene: str | None,
        sub_scene: str | None,
        difficulty: str,
        limit: int,
        exclude_ids: frozenset[str],
        seed: int,
    ) -> list[ContentQuestion]:
        legacy_top_scenes = {"news_podcasts": "news"}
        candidates = [
            question
            for question in self._questions
            if (
                top_scene is None
                or (
                    question.top_scene
                    or legacy_top_scenes.get(question.category, question.category)
                )
                == top_scene
            )
            and (sub_scene is None or question.sub_scene == sub_scene)
            and question.difficulty == difficulty
            and question.id not in exclude_ids
        ]
        random.Random(seed).shuffle(candidates)
        return candidates[:limit]

    def get_questions_by_ids(
        self,
        ids: list[str] | tuple[str, ...],
    ) -> list[ContentQuestion]:
        by_id = {question.id: question for question in self._questions}
        return [by_id[question_id] for question_id in ids if question_id in by_id]

    def list_scenes(self) -> list[SceneMetadata]:
        return self._scene_catalog or _scene_catalog()


def _scene_catalog() -> list[SceneMetadata]:
    definitions = [
        (
            "daily",
            "日常生活",
            ("daily_home", "家庭家务"),
            ("daily_social", "社交沟通"),
            ("daily_shopping", "购物服务"),
            ("daily_food", "餐饮烹饪"),
        ),
        (
            "travel",
            "出行旅行",
            ("travel_transport", "交通通勤"),
            ("travel_directions", "问路导航"),
            ("travel_hotel", "酒店住宿"),
            ("travel_tourism", "旅行观光"),
        ),
        (
            "work",
            "职场商务",
            ("work_office", "办公协作"),
            ("work_meetings", "会议演示"),
            ("work_contact", "邮件电话"),
            ("work_jobs", "求职面试"),
        ),
        (
            "study",
            "学习考试",
            ("study_campus", "校园课堂"),
            ("study_exams", "考试备考"),
            ("study_academic", "学术研究"),
            ("study_language", "语言学习"),
        ),
        (
            "health",
            "健康医疗",
            ("health_clinic", "医院就诊"),
            ("health_pharmacy", "药店用药"),
            ("health_fitness", "健身运动"),
            ("health_wellbeing", "身心健康"),
        ),
        (
            "technology",
            "科技科学",
            ("technology_devices", "数码设备"),
            ("technology_software", "互联网软件"),
            ("technology_engineering", "工程技术"),
            ("technology_science", "科学科普"),
        ),
        (
            "culture",
            "文化娱乐",
            ("culture_movies", "影视戏剧"),
            ("culture_music", "音乐艺术"),
            ("culture_books", "阅读文学"),
            ("culture_sports", "体育休闲"),
        ),
        (
            "news",
            "新闻社会",
            ("news_current", "时事新闻"),
            ("news_business", "财经商业"),
            ("news_public", "法律公共事务"),
            ("news_environment", "环境社会"),
        ),
    ]
    return [
        SceneMetadata(
            key=key,
            label=label,
            children=tuple(
                SceneMetadata(key=child_key, label=child_label)
                for child_key, child_label in children
            ),
        )
        for key, label, *children in definitions
    ]


def _process_qml_events(count: int = 8) -> None:
    for _ in range(count):
        QCoreApplication.processEvents()


def _visual_descendants(item):
    for child in item.childItems():
        yield child
        yield from _visual_descendants(child)


def _find_visual_item(root, object_name: str):
    visual_root = root if hasattr(root, "childItems") else root.contentItem()
    return next(
        (
            item
            for item in _visual_descendants(visual_root)
            if item.objectName() == object_name
        ),
        None,
    )


def _mouse_click_item(window, item) -> None:
    center = item.mapToItem(
        window.contentItem(), QPointF(item.width() / 2, item.height() / 2)
    )
    QTest.mouseClick(
        window,
        Qt.LeftButton,
        Qt.NoModifier,
        QPoint(round(center.x()), round(center.y())),
    )
    _process_qml_events()


def _load_dashboard_window(
    tmp_path,
    *,
    width: int,
    height: int,
    scene_catalog: list[SceneMetadata] | None = None,
):
    application = QApplication.instance() or QApplication([])
    assert application is not None
    content_repository = _FakeContentRepository([], scene_catalog)
    user_repository = UserRepository(tmp_path / "user.db")
    controller = PracticeController(
        PracticeEngine(
            content_repository,
            user_repository,
        )
    )
    learning_center = LearningCenterViewModel(
        LearningCenterService(content_repository, user_repository)
    )
    engine = QQmlApplicationEngine()
    engine.setInitialProperties(
        {
            "backend": controller,
            "learning": learning_center,
        }
    )
    engine._learning_center = learning_center
    engine.load(ui_path("Main.qml"))
    assert engine.rootObjects()
    root = engine.rootObjects()[0]
    root.setWidth(width)
    root.setHeight(height)
    _process_qml_events(12)
    return engine, root, controller


@pytest.mark.qt_serial
def test_learning_dashboard_matches_confirmed_page_structure(tmp_path, qtbot) -> None:
    engine, root, _controller = _load_dashboard_window(
        tmp_path,
        width=1536,
        height=1024,
    )

    sidebar = root.findChild(QQuickItem, "appSidebar")
    sidebar_mascot = root.findChild(QQuickItem, "sidebarMascot")
    assert sidebar is not None
    assert sidebar_mascot is not None
    assert sidebar_mascot.isVisible()
    assert ui_path("assets/sidebar-mascot.png").is_file()
    assert sidebar.width() == pytest.approx(248, abs=4)
    for page_key in (
        "home",
        "practice-config",
        "history",
        "wrong-book",
        "vocabulary",
        "statistics",
        "settings",
    ):
        assert _find_visual_item(root, f"nav_{page_key}") is not None

    for card_name in (
        "resumeCard",
        "dailyGoalCard",
        "practiceConfigurator",
        "pendingCard",
        "recentSessionsCard",
        "trendCard",
        "metric_total",
        "metric_accuracy",
        "metric_streak",
        "metric_duration",
        "metric_pending",
    ):
        card = root.findChild(QQuickItem, card_name)
        assert card is not None
        assert card.isVisible()

    configurator = root.findChild(QQuickItem, "practiceConfigurator")
    difficulty_controls = root.findChild(QQuickItem, "difficultyControls")
    count_controls = root.findChild(QQuickItem, "countControls")
    endless_button = root.findChild(QQuickItem, "startEndlessButton")
    start_button = root.findChild(QQuickItem, "startPracticeButton")
    assert configurator is not None
    assert difficulty_controls is not None
    assert count_controls is not None
    assert endless_button is not None
    assert start_button is not None
    difficulty_position = difficulty_controls.mapToItem(
        configurator,
        QPointF(0, 0),
    )
    count_position = count_controls.mapToItem(configurator, QPointF(0, 0))
    endless_position = endless_button.mapToItem(configurator, QPointF(0, 0))
    start_position = start_button.mapToItem(configurator, QPointF(0, 0))
    assert difficulty_position.y() < count_position.y()
    assert count_position.y() + 15 < endless_position.y()
    assert endless_position.y() < count_position.y() + 36
    assert endless_position.y() + endless_button.height() < start_position.y()
    assert start_button.width() == pytest.approx(508, abs=4)

    assert root.findChild(QQuickItem, "practicePreview") is None
    del engine


@pytest.mark.qt_serial
def test_learning_dashboard_compacts_and_scrolls_at_minimum_window(tmp_path, qtbot) -> None:
    engine, root, _controller = _load_dashboard_window(
        tmp_path,
        width=960,
        height=700,
    )

    sidebar = root.findChild(QQuickItem, "appSidebar")
    dashboard_scroll = root.findChild(QQuickItem, "homeScroll")
    start_button = root.findChild(QQuickItem, "startPracticeButton")
    assert sidebar is not None
    assert sidebar.width() <= 84
    assert dashboard_scroll is not None
    assert start_button is not None
    assert dashboard_scroll.property("contentWidth") == pytest.approx(
        dashboard_scroll.width(),
        abs=1,
    )
    assert dashboard_scroll.property("contentHeight") > dashboard_scroll.height()
    del engine


@pytest.mark.qt_serial
@pytest.mark.parametrize(
    ("route", "page_name", "required_names"),
    [
        (
            "history",
            "learningHistoryPage",
            ("historyFilter_all", "historyList", "historyEmptyState"),
        ),
        (
            "wrong-book",
            "wrongBookPage",
            ("wrongSearch", "startWrongReview", "wrongBookEmptyState"),
        ),
        (
            "vocabulary",
            "vocabularyPage",
            (
                "vocabularySearch",
                "startVocabularyReview",
                "vocabularyEmptyState",
            ),
        ),
        (
            "statistics",
            "statisticsPage",
            (
                "statisticsRange_7d",
                "statisticsTrend",
                "statisticsTrendEmptyState",
            ),
        ),
    ],
)
def test_sidebar_routes_to_complete_learning_pages(
    tmp_path,
    qtbot,
    route: str,
    page_name: str,
    required_names: tuple[str, ...],
) -> None:
    engine, root, _controller = _load_dashboard_window(
        tmp_path,
        width=1536,
        height=1024,
    )
    navigation_button = _find_visual_item(root, f"nav_{route}")
    assert navigation_button is not None
    QMetaObject.invokeMethod(navigation_button, "click")
    _process_qml_events()

    page = root.findChild(QQuickItem, page_name)
    assert page is not None
    assert page.isVisible()
    for object_name in required_names:
        assert (
            root.findChild(QQuickItem, object_name) is not None
            or _find_visual_item(root, object_name) is not None
        )
    del engine


@pytest.mark.qt_serial
def test_learning_settings_returns_to_the_page_that_opened_it(tmp_path, qtbot) -> None:
    engine, root, _controller = _load_dashboard_window(
        tmp_path,
        width=1536,
        height=1024,
    )
    QMetaObject.invokeMethod(_find_visual_item(root, "nav_history"), "click")
    _process_qml_events()
    QMetaObject.invokeMethod(_find_visual_item(root, "nav_settings"), "click")
    _process_qml_events()

    done_buttons = [
        item
        for item in _visual_descendants(root.contentItem())
        if item.objectName() == "settingsDoneButton" and item.isVisible()
    ]
    assert len(done_buttons) == 1
    QMetaObject.invokeMethod(done_buttons[0], "click")
    _process_qml_events()

    history_page = root.findChild(QQuickItem, "learningHistoryPage")
    assert history_page is not None
    assert history_page.isVisible()
    del engine


@pytest.mark.qt_serial
def test_dashboard_scene_selector_matches_confirmed_compact_controls(
    tmp_path,
    qtbot,
) -> None:
    cet_scene = SceneMetadata(
        key="cet",
        label="四六级考试",
        children=(
            SceneMetadata(key="cet_cet4", label="四级 CET-4"),
            SceneMetadata(key="cet_cet6", label="六级 CET-6"),
        ),
    )
    engine, root, controller = _load_dashboard_window(
        tmp_path,
        width=1536,
        height=1024,
        scene_catalog=[*_scene_catalog(), cet_scene],
    )

    selector = root.findChild(QQuickItem, "dashboardSceneSelector")
    assert selector is not None
    for key in ("daily", "study", "culture", "news"):
        assert _find_visual_item(root, f"topScene_{key}") is not None
    assert _find_visual_item(root, "moreSceneButton") is not None
    assert root.findChild(QQuickItem, "allSubScenes") is not None
    all_scenes = root.findChild(QQuickItem, "allScenes")
    all_sub_scenes = root.findChild(QQuickItem, "allSubScenes")
    assert all_scenes is not None
    assert all_sub_scenes is not None
    assert not all_scenes.isVisible()
    assert all_sub_scenes.isVisible()
    assert all_sub_scenes.property("text") == "全部"

    def visible_cet_level_chips() -> list[QQuickItem]:
        return [
            item
            for item in _visual_descendants(root.contentItem())
            if item.isVisible()
            and item.metaObject().className().startswith("ChoiceChip_")
            and item.property("text") in {"四级 CET-4", "六级 CET-6"}
        ]

    assert controller.selectedTopScene == "daily"
    assert visible_cet_level_chips() == []

    QMetaObject.invokeMethod(_find_visual_item(root, "topScene_study"), "clicked")
    _process_qml_events()
    assert controller.selectedTopScene == "study"
    assert visible_cet_level_chips() == []

    QMetaObject.invokeMethod(_find_visual_item(root, "moreSceneButton"), "clicked")
    _process_qml_events()
    QMetaObject.invokeMethod(_find_visual_item(root, "topScene_cet"), "clicked")
    _process_qml_events()
    assert controller.selectedTopScene == "cet"
    assert len(visible_cet_level_chips()) == 2
    del engine


@pytest.mark.qt_serial
def test_home_scene_selector_uses_controller_catalog_and_starts_with_both_keys(
    tmp_path, qtbot, qtlog
) -> None:
    question = ContentQuestion(
        id="q-scene-selector",
        sentence_id="s-scene-selector",
        sentence_text="We checked into the hotel.",
        category="travel",
        top_scene="travel",
        sub_scene="travel_hotel",
        source_url="https://example.test/scene-selector",
        normalized_hash="scene-selector-hash",
        difficulty="easy",
        answer_start=3,
        answer_end=10,
        canonical_answer="checked",
        answer_word_count=1,
        difficulty_score=1.0,
        rationale="两级场景选择测试",
        aliases=(),
    )
    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository(
                [
                    replace(
                        question,
                        id=f"q-scene-selector-{index}",
                        sentence_id=f"s-scene-selector-{index}",
                        normalized_hash=f"scene-selector-hash-{index}",
                    )
                    for index in range(10)
                ]
            ),
            UserRepository(tmp_path / "user.db"),
        )
    )
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    root.setWidth(1024)
    root.setHeight(700)
    _process_qml_events()

    top_daily = _find_visual_item(root, "topScene_daily")
    top_news = _find_visual_item(root, "topScene_news")
    top_travel = _find_visual_item(root, "topScene_travel")
    all_sub_scenes = root.findChild(QQuickItem, "allSubScenes")
    all_scenes = root.findChild(QQuickItem, "allScenes")
    assert top_daily is not None
    assert top_news is not None
    assert top_travel is not None
    assert all_sub_scenes is not None
    assert all_scenes is not None
    top_scene_items = [
        item
        for item in _visual_descendants(root.contentItem())
        if item.objectName().startswith("topScene_")
    ]
    assert len(top_scene_items) == 8
    assert len({round(item.y()) for item in top_scene_items}) >= 1

    QMetaObject.invokeMethod(top_daily, "clicked")
    _process_qml_events()
    assert controller.selectedTopScene == ""
    assert controller.selectedSubScene == ""
    assert all_scenes.property("selected") is True

    home_scroll = root.findChild(QQuickItem, "homeScroll")
    assert home_scroll is not None
    news_position = top_news.mapToItem(home_scroll, QPointF(0, 0))
    if news_position.y() + top_news.height() > home_scroll.height():
        home_scroll.setProperty(
            "contentY",
            min(
                home_scroll.property("contentHeight") - home_scroll.height(),
                home_scroll.property("contentY")
                + news_position.y()
                - home_scroll.height()
                + top_news.height()
                + 12,
            ),
        )
        _process_qml_events()

    _mouse_click_item(root, top_news)
    assert controller.selectedTopScene == "news"
    assert controller.selectedSubScene == ""
    assert top_news.property("selected") is True

    QMetaObject.invokeMethod(top_travel, "clicked")
    _process_qml_events()
    travel_hotel = _find_visual_item(root, "subScene_travel_hotel")
    assert travel_hotel is not None
    travel_children = [
        item
        for item in _visual_descendants(root.contentItem())
        if item.objectName().startswith("subScene_travel_")
    ]
    assert len(travel_children) == 4
    QMetaObject.invokeMethod(travel_hotel, "clicked")
    _process_qml_events()
    assert controller.selectedTopScene == "travel"
    assert controller.selectedSubScene == "travel_hotel"
    QMetaObject.invokeMethod(all_sub_scenes, "clicked")
    _process_qml_events()
    assert controller.selectedSubScene == ""
    QMetaObject.invokeMethod(travel_hotel, "clicked")
    _process_qml_events()

    start_button = root.findChild(QQuickItem, "startPracticeButton")
    assert start_button is not None
    QMetaObject.invokeMethod(start_button, "click")
    _process_qml_events()
    assert controller.currentPage == "practice"
    assert controller.sceneLabel == "出行旅行 / 酒店住宿"
    header_scene = root.findChild(QQuickItem, "headerSceneLabel")
    assert header_scene is not None
    assert header_scene.property("text") == controller.sceneLabel
    assert not any("Binding loop" in record.message for record in qtlog.records)


@pytest.mark.qt_serial
def test_home_scene_selector_remains_reachable_at_compact_window_and_starts_endless(
    tmp_path, qtbot
) -> None:
    questions = [
        ContentQuestion(
            id=f"q-endless-{index}",
            sentence_id=f"s-endless-{index}",
            sentence_text="We checked into the hotel.",
            category="travel",
            top_scene="travel",
            sub_scene="travel_hotel",
            source_url=f"https://example.test/endless/{index}",
            normalized_hash=f"endless-hash-{index}",
            difficulty="easy",
            answer_start=3,
            answer_end=10,
            canonical_answer="checked",
            answer_word_count=1,
            difficulty_score=1.0,
            rationale="无尽场景选择测试",
            aliases=(),
        )
        for index in range(3)
    ]
    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository(questions),
            UserRepository(tmp_path / "user.db"),
        )
    )
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    root.setWidth(1024)
    root.setHeight(700)
    _process_qml_events()

    home_scroll = root.findChild(QQuickItem, "homeScroll")
    start_button = root.findChild(QQuickItem, "startPracticeButton")
    endless_button = root.findChild(QQuickItem, "startEndlessButton")
    assert root.width() == 1024
    assert home_scroll is not None
    assert start_button is not None
    assert endless_button is not None

    button_position = start_button.mapToItem(home_scroll, QPointF(0, 0))
    initially_visible = button_position.y() + start_button.height() <= home_scroll.height()
    if not initially_visible:
        maximum_y = home_scroll.property("contentHeight") - home_scroll.height()
        assert maximum_y > 0
        home_scroll.setProperty("contentY", maximum_y)
        _process_qml_events()
        button_position = start_button.mapToItem(home_scroll, QPointF(0, 0))
        assert button_position.y() + start_button.height() <= home_scroll.height()

    QMetaObject.invokeMethod(_find_visual_item(root, "topScene_travel"), "clicked")
    _process_qml_events()
    QMetaObject.invokeMethod(
        _find_visual_item(root, "subScene_travel_hotel"), "clicked"
    )
    _process_qml_events()
    QMetaObject.invokeMethod(endless_button, "click")
    _process_qml_events()
    assert controller.currentPage == "practice"
    assert controller.sceneLabel == "出行旅行 / 酒店住宿"


def test_home_qml_no_longer_contains_the_legacy_four_category_model() -> None:
    source = ui_path("HomePage.qml").read_text(encoding="utf-8")

    assert "news_podcasts" not in source
    assert "selectedCategory" not in source
    assert "sceneCatalog" in source


@pytest.mark.qt_serial
def test_scene_selector_reflows_to_three_columns_at_narrow_component_width(
    tmp_path, qtbot
) -> None:
    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository([]),
            UserRepository(tmp_path / "user.db"),
        )
    )
    engine = QQmlApplicationEngine()
    component = QQmlComponent(engine)
    component.loadUrl(QUrl.fromLocalFile(str(ui_path("SceneSelector.qml"))))
    selector = component.createWithInitialProperties({"controller": controller})
    assert selector is not None, [error.toString() for error in component.errors()]
    window = QQuickWindow()
    window.resize(360, 500)
    selector.setParentItem(window.contentItem())
    selector.setWidth(360)
    window.show()
    _process_qml_events()

    top_flow = selector.findChild(QQuickItem, "topSceneFlow")
    top_scene_items = [
        item
        for item in _visual_descendants(selector)
        if item.objectName().startswith("topScene_")
    ]
    assert top_flow is not None
    assert len(top_scene_items) == 8
    row_positions = {round(item.y()) for item in top_scene_items}
    assert len(row_positions) == 3
    assert sorted(
        sum(round(item.y()) == row_position for item in top_scene_items)
        for row_position in row_positions
    ) == [2, 3, 3]
    assert top_flow.height() == 136
    assert max(item.x() + item.width() for item in top_scene_items) <= selector.width()


@pytest.mark.qt_serial
def test_compact_practice_header_keeps_essential_controls_inside_window(
    tmp_path, qtbot
) -> None:
    question = ContentQuestion(
        id="q-compact-header",
        sentence_id="s-compact-header",
        sentence_text="Engineers tested the software carefully.",
        category="technology",
        top_scene="technology",
        sub_scene="technology_engineering",
        source_url="https://example.test/compact-header",
        normalized_hash="compact-header-hash",
        difficulty="easy",
        answer_start=10,
        answer_end=16,
        canonical_answer="tested",
        answer_word_count=1,
        difficulty_score=1.0,
        rationale="窄屏页头布局测试",
        aliases=(),
    )
    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository([question]),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("technology", "technology_engineering", "easy", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]

    for width in (1024, 960):
        root.setWidth(width)
        root.setHeight(700)
        _process_qml_events()
        for object_name in (
            "backHomeButton",
            "headerDifficulty",
            "headerSceneLabel",
            "headerProgress",
            "settingsButton",
        ):
            item = root.findChild(QQuickItem, object_name)
            assert item is not None
            assert item.property("visible") is True
            position = item.mapToItem(root.contentItem(), QPointF(0, 0))
            assert position.x() >= 0
            assert position.x() + item.width() <= width

        offline_badge = root.findChild(QQuickItem, "offlineBadge")
        assert offline_badge is not None
        assert offline_badge.property("visible") is False


def test_main_qml_uses_empty_scene_placeholder_without_backend() -> None:
    source = ui_path("Main.qml").read_text(encoding="utf-8")

    assert 'appWindow.backend ? appWindow.backend.sceneLabel : ""' in source


@pytest.mark.qt_serial
def test_main_qml_loads_and_exposes_primary_practice_controls(qtbot, qtlog) -> None:
    application = QApplication.instance() or QApplication([])
    assert application is not None
    engine = QQmlApplicationEngine()

    engine.load(ui_path("Main.qml"))

    assert len(engine.rootObjects()) == 1
    root = engine.rootObjects()[0]
    expected_names = {
        "homePage",
        "practicePage",
        "playButton",
        "backHomeButton",
        "replayShortcut",
        "audioToolbar",
        "speedSelector",
        "answerFields",
        "translationPanel",
        "translationToggleButton",
        "submitButton",
        "mascot",
        "progressTrack",
        "repairPage",
        "resumeButton",
        "settingsDoneButton",
        "audioErrorPanel",
        "resetConfirmation",
    }
    actual_names = {child.objectName() for child in root.findChildren(QObject)}
    assert expected_names <= actual_names
    assert not any("Binding loop" in record.message for record in qtlog.records)


def test_mascot_qml_implements_distinct_feedback_animations() -> None:
    source = ui_path("WaveMascot.qml").read_text(encoding="utf-8")

    for animation in (
        "bounce_wave",
        "clap",
        "spin",
        "stretch_wave",
        "confetti",
        "droop",
        "shake_head",
        "shrink_wave",
        "crouch",
        "sway",
        "level_up_rise",
        "level_down_soft",
    ):
        assert f'animationName === "{animation}"' in source


def test_practice_uses_audible_sound_effect_instead_of_silent_media_player() -> None:
    source = ui_path("PracticePage.qml").read_text(encoding="utf-8")

    assert "SoundEffect {" in source
    assert "MediaPlayer {" not in source


def test_replay_stops_current_audio_before_starting_a_new_playback() -> None:
    source = ui_path("PracticePage.qml").read_text(encoding="utf-8")

    restart_body = source.split("function restartAudioPlayback()", maxsplit=1)[1].split(
        "\n    }", maxsplit=1
    )[0]
    assert restart_body.index("soundEffect.stop()") < restart_body.index(
        "page.scheduleReadyPlayback(generation)"
    )
    assert "playbackGeneration" in restart_body
    assert "Qt.callLater" in source


def test_practice_wraps_long_sentences_and_scales_the_waveform() -> None:
    source = ui_path("PracticePage.qml").read_text(encoding="utf-8")
    waveform_source = ui_path("Waveform.qml").read_text(encoding="utf-8")

    assert "Flow {" in source
    assert "wrapMode: Text.Wrap" in source
    assert "sentenceLength" in source
    assert "denseQuestionLayout" in source
    assert "waveformScale" in source
    assert "ScrollView {" in source
    assert "ScrollBar.vertical.policy: ScrollBar.AsNeeded" in source
    assert "barSpacing: 4" in waveform_source
    assert "Math.pow(waveform.levels[sourceIndex], 1.65) * 72" in waveform_source


def test_practice_matches_the_selected_focus_workbench_shell() -> None:
    main_source = ui_path("Main.qml").read_text(encoding="utf-8")
    practice_source = ui_path("PracticePage.qml").read_text(encoding="utf-8")

    assert "practiceShellVisible" in main_source
    assert 'objectName: "headerDifficulty"' in main_source
    assert 'objectName: "headerSceneLabel"' in main_source
    assert 'objectName: "headerProgress"' in main_source
    assert 'objectName: "endSessionButton"' in main_source
    assert 'objectName: "offlineBadge"' in main_source
    assert 'currentPage: "practice-config"' in main_source
    assert 'objectName: "practiceCard"' in practice_source
    assert 'objectName: "progressTrack"' in practice_source
    assert 'objectName: "shortcutHint"' in practice_source
    assert "FeedbackMascot {" in practice_source


def test_practice_exposes_replay_shortcuts_for_mac_and_other_platforms() -> None:
    source = ui_path("PracticePage.qml").read_text(encoding="utf-8")

    assert 'sequence: "Ctrl+R"' in source
    assert 'sequence: "Meta+R"' in source
    assert 'sequence: "Space"' in source
    assert 'Qt.platform.os === "osx"' in source


def test_practice_shows_chinese_translation_after_reveal_or_correct_answer() -> None:
    source = ui_path("PracticePage.qml").read_text(encoding="utf-8")

    assert "中文翻译" in source
    assert "page.translationPreviewVisible || page.visualCorrect" in source
    assert 'page.state === "revealed"' in source
    assert "sentenceTranslation" in source
    assert "page.translationPreviewVisible = false" in source


@pytest.mark.qt_serial
def test_practice_layout_never_expands_beyond_the_window(tmp_path, qtbot) -> None:
    question = ContentQuestion(
        id="q-layout",
        sentence_id="s-layout",
        sentence_text="We wanted to talk about Tom.",
        category="daily",
        source_url="https://example.test/layout",
        normalized_hash="layout-hash",
        difficulty="hard",
        answer_start=13,
        answer_end=23,
        canonical_answer="talk about",
        answer_word_count=2,
        difficulty_score=3.0,
        rationale="布局回归测试",
        aliases=(),
        translation_zh="我们想谈谈汤姆。",
    )

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository([question]),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "hard", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    root.setWidth(1984)
    root.setHeight(1278)
    for _ in range(10):
        QCoreApplication.processEvents()

    practice = root.findChild(QQuickItem, "practicePage")
    answer_fields = root.findChild(QQuickItem, "answerFields")
    audio_toolbar = root.findChild(QQuickItem, "audioToolbar")
    audio_player_panel = root.findChild(QQuickItem, "audioPlayerPanel")
    play_button = root.findChild(QQuickItem, "playButton")
    waveform = root.findChild(QQuickItem, "practiceWaveform")
    replay_button = root.findChild(QQuickItem, "replayButton")
    replay_icon = root.findChild(QQuickItem, "replayIcon")
    replay_label = root.findChild(QQuickItem, "replayLabel")
    speed_selector = root.findChild(QQuickItem, "speedSelector")

    assert practice is not None
    assert answer_fields is not None
    assert audio_toolbar is not None
    assert audio_player_panel is not None
    assert play_button is not None
    assert waveform is not None
    assert replay_button is not None
    assert replay_icon is not None
    assert replay_label is not None
    assert speed_selector is not None
    assert answer_fields.width() <= practice.width()
    assert audio_toolbar.width() <= 430
    assert audio_player_panel.width() <= practice.width()
    assert waveform.width() <= practice.width()
    for audio_control in (
        play_button,
        waveform,
        replay_button,
        speed_selector,
    ):
        position = audio_control.mapToItem(audio_player_panel, QPointF(0, 0))
        assert position.x() >= 0
        assert position.y() >= 0
        assert position.x() + audio_control.width() <= audio_player_panel.width()
        assert position.y() + audio_control.height() <= audio_player_panel.height()

    icon_center = replay_icon.mapToItem(
        replay_button,
        QPointF(replay_icon.width() / 2, replay_icon.height() / 2),
    )
    label_center = replay_label.mapToItem(
        replay_button,
        QPointF(replay_label.width() / 2, replay_label.height() / 2),
    )
    assert abs(icon_center.y() - label_center.y()) <= 1


@pytest.mark.qt_serial
def test_practice_clears_reused_answer_fields_when_question_changes(tmp_path, qtbot) -> None:
    questions = [
        ContentQuestion(
            id="q-one",
            sentence_id="s-one",
            sentence_text="We wanted to talk about Tom.",
            category="daily",
            source_url="https://example.test/one",
            normalized_hash="one-hash",
            difficulty="hard",
            answer_start=13,
            answer_end=23,
            canonical_answer="talk about",
            answer_word_count=2,
            difficulty_score=3.0,
            rationale="输入框复用测试",
            aliases=(),
        ),
        ContentQuestion(
            id="q-two",
            sentence_id="s-two",
            sentence_text="I promise I will never hurt you.",
            category="daily",
            source_url="https://example.test/two",
            normalized_hash="two-hash",
            difficulty="hard",
            answer_start=10,
            answer_end=19,
            canonical_answer="will never",
            answer_word_count=2,
            difficulty_score=3.0,
            rationale="输入框复用测试",
            aliases=(),
        ),
    ]
    questions.extend(
        replace(
            questions[0],
            id=f"q-extra-{index}",
            sentence_id=f"s-extra-{index}",
            normalized_hash=f"extra-hash-{index}",
        )
        for index in range(3)
    )

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository(questions),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "hard", 5)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    for _ in range(5):
        QCoreApplication.processEvents()

    answer_fields = root.findChild(QQuickItem, "answerFields")

    def visual_descendants(item):
        for child in item.childItems():
            yield child
            yield from visual_descendants(child)

    inputs = [
        item
        for item in visual_descendants(answer_fields)
        if item.objectName().startswith("answerInput")
    ]
    assert len(inputs) == 2

    controller.revealAnswer()
    QCoreApplication.processEvents()
    assert all(item.property("text") for item in inputs)

    controller.nextQuestion()
    QCoreApplication.processEvents()

    assert all(item.property("text") == "" for item in inputs)


@pytest.mark.qt_serial
def test_space_moves_focus_to_the_next_answer_field_without_being_entered(
    tmp_path, qtbot
) -> None:
    sentence = "They pass many experimental tests today."
    answer = "pass many experimental tests"
    question = ContentQuestion(
        id="q-space-focus",
        sentence_id="s-space-focus",
        sentence_text=sentence,
        category="daily",
        source_url="https://example.test/space-focus",
        normalized_hash="space-focus-hash",
        difficulty="hard",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=4,
        difficulty_score=3.0,
        rationale="空格切换输入框测试",
        aliases=(),
    )

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository([question]),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "hard", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    for _ in range(5):
        QCoreApplication.processEvents()

    answer_fields = root.findChild(QQuickItem, "answerFields")

    def visual_descendants(item):
        for child in item.childItems():
            yield child
            yield from visual_descendants(child)

    inputs = sorted(
        (
            item
            for item in visual_descendants(answer_fields)
            if item.objectName().startswith("answerInput")
        ),
        key=lambda item: item.objectName(),
    )
    assert len(inputs) == 4

    inputs[0].forceActiveFocus()
    for key, text in ((Qt.Key_J, "j"), (Qt.Key_J, "j"), (Qt.Key_S, "s")):
        QCoreApplication.sendEvent(
            inputs[0], QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text)
        )
    QCoreApplication.sendEvent(
        inputs[0], QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " ")
    )
    QCoreApplication.processEvents()

    assert inputs[0].property("text") == "jjs"
    assert inputs[1].property("activeFocus") is True


@pytest.mark.qt_serial
def test_long_idle_question_keeps_core_actions_visible_without_scrolling(
    tmp_path, qtbot, qtlog
) -> None:
    sentence = (
        "As a person having my own business, it can fully express myself "
        "and make my own decisions, a privilege not everyone can have, "
        "even those with highly-paid positions."
    )
    answer = "everyone"
    question = ContentQuestion(
        id="q-long-first-screen",
        sentence_id="s-long-first-screen",
        sentence_text=sentence,
        category="daily",
        source_url="https://example.test/long-first-screen",
        normalized_hash="long-first-screen-hash",
        difficulty="hard",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=1,
        difficulty_score=3.0,
        rationale="长句首屏布局测试",
        aliases=(),
        translation_zh="作为一个拥有自己事业的人，我可以充分表达自己并作出决定。",
    )

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository([question]),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "hard", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    root.setWidth(1536)
    root.setHeight(1024)
    for _ in range(10):
        QCoreApplication.processEvents()

    practice_scroll = root.findChild(QQuickItem, "practiceScroll")
    submit_button = root.findChild(QQuickItem, "submitButton")
    translation_button = root.findChild(QQuickItem, "translationToggleButton")
    shortcut_hint = root.findChild(QQuickItem, "shortcutHint")

    assert practice_scroll is not None
    assert submit_button is not None
    assert translation_button is not None
    assert shortcut_hint is not None
    flickable = practice_scroll.property("contentItem")
    assert flickable.property("contentY") == 0

    for core_action in (submit_button, translation_button, shortcut_hint):
        position = core_action.mapToItem(practice_scroll, QPointF(0, 0))
        assert position.y() >= 0
        assert (
            position.y() + core_action.height()
            <= practice_scroll.height() - 12
        )

    assert not any("Binding loop" in record.message for record in qtlog.records)


@pytest.mark.qt_serial
def test_overflowing_practice_content_can_scroll_until_submit_button_is_visible(
    tmp_path, qtbot, qtlog
) -> None:
    sentence = (
        'Brown responded by saying that "a million people come from Europe, '
        'but a million people, British people, have gone into Europe."'
    )
    answer = "people come from Europe"
    question = ContentQuestion(
        id="q-scroll",
        sentence_id="s-scroll",
        sentence_text=sentence,
        category="news_podcasts",
        source_url="https://example.test/scroll",
        normalized_hash="scroll-hash",
        difficulty="hard",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=4,
        difficulty_score=3.0,
        rationale="练习内容滚动测试",
        aliases=(),
        translation_zh="布朗回应说，一百万人来自欧洲，但有一百万英国人进入了欧洲。",
    )

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository([question]),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("news_podcasts", "hard", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    root.setWidth(1500)
    root.setHeight(760)
    controller.revealAnswer()
    for _ in range(10):
        QCoreApplication.processEvents()

    practice_scroll = root.findChild(QQuickItem, "practiceScroll")
    submit_button = root.findChild(QQuickItem, "submitButton")

    assert practice_scroll is not None
    assert submit_button is not None
    flickable = practice_scroll.property("contentItem")
    assert flickable.property("contentHeight") > flickable.height()

    maximum_y = flickable.property("contentHeight") - flickable.height()
    flickable.setProperty("contentY", maximum_y)
    QCoreApplication.processEvents()
    button_position = submit_button.mapToItem(practice_scroll, QPointF(0, 0))

    assert button_position.y() + submit_button.height() <= practice_scroll.height()
    assert not any("Binding loop" in record.message for record in qtlog.records)

    root.setWidth(960)
    root.setHeight(700)
    for _ in range(10):
        QCoreApplication.processEvents()
    maximum_y = flickable.property("contentHeight") - flickable.height()
    flickable.setProperty("contentY", maximum_y)
    QCoreApplication.processEvents()
    compact_button_position = submit_button.mapToItem(
        practice_scroll, QPointF(0, 0)
    )
    progress_track = root.findChild(QQuickItem, "progressTrack")

    assert maximum_y > 0
    assert (
        compact_button_position.y() + submit_button.height()
        <= practice_scroll.height()
    )
    assert progress_track is not None
    assert progress_track.y() + progress_track.height() <= root.height()


@pytest.mark.qt_serial
def test_home_round_trip_keeps_the_unsubmitted_answer_draft(tmp_path, qtbot) -> None:
    sentence = "They pass many tests today."
    answer = "pass many"
    question = ContentQuestion(
        id="q-home-round-trip",
        sentence_id="s-home-round-trip",
        sentence_text=sentence,
        category="daily",
        source_url="https://example.test/home-round-trip",
        normalized_hash="home-round-trip-hash",
        difficulty="easy",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=2,
        difficulty_score=1.0,
        rationale="主页往返测试",
        aliases=(),
    )

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository([question]),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "easy", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    for _ in range(5):
        QCoreApplication.processEvents()

    back_button = root.findChild(QQuickItem, "backHomeButton")
    resume_button = root.findChild(QQuickItem, "resumeButton")
    answer_fields = root.findChild(QQuickItem, "answerFields")

    def visual_descendants(item):
        for child in item.childItems():
            yield child
            yield from visual_descendants(child)

    first_input = next(
        item
        for item in visual_descendants(answer_fields)
        if item.objectName() == "answerInput0"
    )
    assert back_button is not None
    assert resume_button is not None
    first_input.setProperty("text", "draft")

    QMetaObject.invokeMethod(back_button, "click")
    QCoreApplication.processEvents()

    assert controller.currentPage == "home"
    assert resume_button.property("visible") is True

    QMetaObject.invokeMethod(resume_button, "click")
    QCoreApplication.processEvents()

    assert controller.currentPage == "practice"
    assert first_input.property("text") == "draft"


@pytest.mark.qt_serial
def test_replay_shortcut_invokes_replay_without_using_the_mouse(tmp_path, qtbot) -> None:
    sentence = "They listen today."
    answer = "listen"
    question = ContentQuestion(
        id="q-replay-shortcut",
        sentence_id="s-replay-shortcut",
        sentence_text=sentence,
        category="daily",
        source_url="https://example.test/replay-shortcut",
        normalized_hash="replay-shortcut-hash",
        difficulty="easy",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=1,
        difficulty_score=1.0,
        rationale="重听快捷键测试",
        aliases=(),
    )

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository([question]),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "easy", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    QCoreApplication.processEvents()

    replay_shortcut = root.findChild(QObject, "replayShortcut")
    assert replay_shortcut is not None
    assert str(replay_shortcut.property("sequence")) == "Ctrl+R"

    QMetaObject.invokeMethod(replay_shortcut, "activated")
    QCoreApplication.processEvents()

    assert controller.replayCount == 1


@pytest.mark.qt_serial
def test_correct_answer_reveals_the_full_sentence_translation(tmp_path, qtbot) -> None:
    sentence = "They listen today."
    answer = "listen"
    question = ContentQuestion(
        id="q-correct-translation",
        sentence_id="s-correct-translation",
        sentence_text=sentence,
        category="daily",
        source_url="https://example.test/correct-translation",
        normalized_hash="correct-translation-hash",
        difficulty="easy",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=1,
        difficulty_score=1.0,
        rationale="正确答案翻译测试",
        aliases=(),
        translation_zh="他们今天听了。",
    )

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository([question]),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "easy", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    QCoreApplication.processEvents()

    translation_panel = root.findChild(QQuickItem, "translationPanel")
    assert translation_panel is not None
    assert translation_panel.property("visible") is False

    controller.submitAnswers(["listen"])
    QCoreApplication.processEvents()

    assert translation_panel.property("visible") is True


@pytest.mark.qt_serial
def test_translation_button_only_toggles_translation_visibility(tmp_path, qtbot) -> None:
    sentence = "They listen today."
    answer = "listen"
    question = ContentQuestion(
        id="q-translation-preview",
        sentence_id="s-translation-preview",
        sentence_text=sentence,
        category="daily",
        source_url="https://example.test/translation-preview",
        normalized_hash="translation-preview-hash",
        difficulty="easy",
        answer_start=sentence.index(answer),
        answer_end=sentence.index(answer) + len(answer),
        canonical_answer=answer,
        answer_word_count=1,
        difficulty_score=1.0,
        rationale="翻译预览不改变答题状态",
        aliases=(),
        translation_zh="他们今天听了。",
    )

    application = QApplication.instance() or QApplication([])
    assert application is not None
    controller = PracticeController(
        PracticeEngine(
            _FakeContentRepository([question]),
            UserRepository(tmp_path / "user.db"),
        )
    )
    controller.startQuantitative("daily", "easy", 1)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": controller})
    engine.load(ui_path("Main.qml"))
    root = engine.rootObjects()[0]
    QCoreApplication.processEvents()

    translation_button = root.findChild(QQuickItem, "translationToggleButton")
    translation_panel = root.findChild(QQuickItem, "translationPanel")
    answer_input = _find_visual_item(root, "answerInput0")
    assert translation_button is not None
    assert translation_panel is not None
    assert answer_input is not None
    assert translation_panel.property("visible") is False
    assert answer_input.property("text") == ""
    assert controller.feedbackState == "idle"

    QMetaObject.invokeMethod(translation_button, "clicked")
    QCoreApplication.processEvents()

    assert translation_panel.property("visible") is True
    assert answer_input.property("text") == ""
    assert controller.feedbackState == "idle"
    assert controller.progressStates == ["current"]

    QMetaObject.invokeMethod(translation_button, "clicked")
    QCoreApplication.processEvents()

    assert translation_panel.property("visible") is False
    assert answer_input.property("text") == ""
    assert controller.feedbackState == "idle"
