# Content Library App Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让应用支持 8 大类、32 子场景和 90,000 道题，并通过按需查询保持启动与练习流畅。

**Architecture:** 正式题库把场景从硬编码枚举迁移为数据库元数据；内容仓库提供小批量抽题和按 ID 恢复接口。练习引擎只保留当前练习队列，QML 从 controller 暴露的场景模型渲染两级选择。

**Tech Stack:** Python 3.12、SQLite、PySide6、Qt Quick/QML、pytest、pytest-qt。

## Global Constraints

- 必须兼容现有 300 句题目 ID、学习记录和未完成任务。
- 定量练习与无尽模式共用大类和子场景选择。
- 应用不得一次性加载 90,000 道题。
- TTS 仍只预取当前题和后两题。
- 场景元数据不得继续分别硬编码在 QML、Python 枚举和 SQLite `CHECK` 中。

---

### Task 1: 升级正式题库结构和发布构建器

**Files:**
- Create: `tools/content_pipeline/content_schema.py`
- Modify: `tools/content_pipeline/builder.py`
- Modify: `tools/content_pipeline/models.py`
- Modify: `tests/content_pipeline/test_pipeline.py`
- Modify: `tests/content_pipeline/test_release_data.py`

**Interfaces:**
- Produces: content schema version 2。
- Produces: `build_database(work_db, database_path, report_path, sources_path)`。
- Produces: `stable_sentence_id(text) -> str`。

- [ ] **Step 1: 写入 schema v2 失败测试**

```python
def test_builder_writes_scene_metadata_stable_ids_and_query_indexes(tmp_path) -> None:
    result = build_fixture_database(tmp_path, per_scene=3)
    with sqlite3.connect(result.database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM top_scenes").fetchone()[0] == 8
        assert connection.execute("SELECT COUNT(*) FROM sub_scenes").fetchone()[0] == 32
        sentence_indexes = {row[1] for row in connection.execute("PRAGMA index_list(sentences)")}
        variant_indexes = {row[1] for row in connection.execute("PRAGMA index_list(question_variants)")}
        assert "idx_sentences_scene_random" in sentence_indexes
        assert "idx_variants_sentence_difficulty" in variant_indexes
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv/bin/pytest tests/content_pipeline/test_pipeline.py -q`

Expected: FAIL，当前 schema 仍为版本 1 且类别为 CHECK 枚举。

- [ ] **Step 3: 实现 schema v2**

正式库必须包含：

```sql
CREATE TABLE top_scenes(key TEXT PRIMARY KEY, label TEXT NOT NULL, sort_order INTEGER NOT NULL);
CREATE TABLE sub_scenes(key TEXT PRIMARY KEY, top_key TEXT NOT NULL REFERENCES top_scenes(key), label TEXT NOT NULL, quota INTEGER NOT NULL, sort_order INTEGER NOT NULL);
CREATE TABLE sentences(id TEXT PRIMARY KEY, text TEXT NOT NULL, translation_zh TEXT NOT NULL, sub_scene_key TEXT NOT NULL REFERENCES sub_scenes(key), source_url TEXT NOT NULL, source_name TEXT NOT NULL, source_author TEXT NOT NULL, source_item_id TEXT NOT NULL, license_name TEXT NOT NULL, license_url TEXT NOT NULL, normalized_hash TEXT NOT NULL UNIQUE, random_key INTEGER NOT NULL);
CREATE TABLE question_variants(id TEXT PRIMARY KEY, sentence_id TEXT NOT NULL REFERENCES sentences(id), difficulty TEXT NOT NULL CHECK(difficulty IN ('easy','medium','hard')), answer_start INTEGER NOT NULL, answer_end INTEGER NOT NULL, canonical_answer TEXT NOT NULL, answer_word_count INTEGER NOT NULL, difficulty_score REAL NOT NULL, rationale TEXT NOT NULL);
CREATE TABLE aliases(id INTEGER PRIMARY KEY AUTOINCREMENT, question_variant_id TEXT NOT NULL REFERENCES question_variants(id), alias TEXT NOT NULL, UNIQUE(question_variant_id, alias));
CREATE INDEX idx_sentences_scene_random ON sentences(sub_scene_key, random_key, id);
CREATE UNIQUE INDEX idx_variants_sentence_difficulty ON question_variants(sentence_id, difficulty);
CREATE INDEX idx_aliases_question ON aliases(question_variant_id);
```

场景过滤通过 `sentences.sub_scene_key` 与 `sub_scenes.top_key` 联表完成。

- [ ] **Step 4: 保留旧 ID 并生成新稳定 ID**

构建器读取现有正式库的 `normalized_hash -> sentence_id` 和旧题别名映射；匹配到的 300 句沿用原 sentence/question ID 与 alias，新句使用 `s_` 加规范化 SHA-256 前 16 位。冲突时扩展至 24 位，不允许添加随机后缀。`random_key` 使用规范化文本 SHA-256 的前 8 字节并屏蔽为正的 63 位整数，禁止使用进程间不稳定的 Python `hash()`。

- [ ] **Step 5: 运行构建测试并提交**

Run: `.venv/bin/pytest tests/content_pipeline/test_pipeline.py tests/content_pipeline/test_release_data.py -q`

Expected: PASS。

```bash
git add tools/content_pipeline/content_schema.py tools/content_pipeline/builder.py tools/content_pipeline/models.py tests/content_pipeline/test_pipeline.py tests/content_pipeline/test_release_data.py
git commit -m "feat: publish hierarchical content database"
```

### Task 2: 增加按需抽题与按 ID 恢复 API

**Files:**
- Modify: `src/listening_cloze/infrastructure/database.py`
- Modify: `tests/infrastructure/test_database.py`

**Interfaces:**
- Produces: `SceneMetadata`。
- Produces: `ContentRepository.list_scenes()`。
- Produces: `ContentRepository.sample_questions(*, top_scene, sub_scene, difficulty, limit, exclude_ids, seed)`。
- Produces: `ContentRepository.get_questions_by_ids(ids)`。

- [ ] **Step 1: 写入仓库失败测试**

```python
def test_repository_samples_small_filtered_batch_without_full_scan(content_db) -> None:
    repository = ContentRepository(content_db)
    rows = repository.sample_questions(
        top_scene="travel", sub_scene="travel_hotel", difficulty="easy",
        limit=10, exclude_ids=frozenset(), seed=1234,
    )
    assert len(rows) == 10
    assert all(row.top_scene == "travel" and row.sub_scene == "travel_hotel" for row in rows)


def test_repository_restores_requested_ids_in_requested_order(content_db) -> None:
    rows = ContentRepository(content_db).get_questions_by_ids(["q3", "q1"])
    assert [row.id for row in rows] == ["q3", "q1"]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv/bin/pytest tests/infrastructure/test_database.py -q`

Expected: FAIL，新 API 尚不存在。

- [ ] **Step 3: 实现小批量查询**

使用 `sentences.random_key` 的两段范围查询：先按场景取 `random_key >= seed` 的句子，再通过 `(sentence_id, difficulty)` 索引连接指定难度；不足部分从最小 random key 补齐。指定大类但未指定子场景时，先由 `sub_scenes` 解析出该大类的 4 个子场景 key，再使用参数化 `IN` 查询，避免扫描全部题目。`exclude_ids` 使用参数化 `NOT IN`，调用方最多传当前队列与本轮已选 ID。`get_questions_by_ids()` 使用单次 `IN` 查询并在 Python 按输入顺序还原。

- [ ] **Step 4: 验证查询计划和提交**

测试用 `EXPLAIN QUERY PLAN` 断言命中 `idx_sentences_scene_random` 和 `idx_variants_sentence_difficulty`，不得出现无条件读取全部 `question_variants`。

Run: `.venv/bin/pytest tests/infrastructure/test_database.py -q`

Expected: PASS。

```bash
git add src/listening_cloze/infrastructure/database.py tests/infrastructure/test_database.py
git commit -m "perf: query content library on demand"
```

### Task 3: 改造领域模型和练习引擎

**Files:**
- Modify: `src/listening_cloze/domain/models.py`
- Modify: `src/listening_cloze/application/practice_engine.py`
- Modify: `tests/application/test_practice_engine.py`

**Interfaces:**
- Produces: `SceneSelection(top_scene: str | None, sub_scene: str | None)`。
- Consumes: Task 2 的 `sample_questions()` 与 `get_questions_by_ids()`。

- [ ] **Step 1: 写入练习引擎失败测试**

```python
def test_quantitative_mode_requests_only_required_candidate_window(engine, content) -> None:
    engine.start_quantitative(
        scene=SceneSelection("travel", "travel_hotel"),
        difficulty=Difficulty.EASY,
        count=10,
    )
    assert content.sample_calls[0]["limit"] <= 50
    assert content.list_all_calls == 0


def test_resume_loads_only_saved_question_ids(engine, content, unfinished_session) -> None:
    assert engine.resume_latest() is True
    assert content.get_by_ids_calls == [unfinished_session.question_ids]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv/bin/pytest tests/application/test_practice_engine.py -q`

Expected: FAIL，当前引擎仍调用 `list_questions()` 全量读取。

- [ ] **Step 3: 移除 Category 枚举依赖并改造抽题**

`Question` 保存 `top_scene` 与 `sub_scene` 字符串；定量模式请求 `max(count * 3, 30)` 个候选后沿用掌握度选择器。无尽模式每次补足 3 题，只排除活动队列。恢复任务只调用 `get_questions_by_ids()`。

- [ ] **Step 4: 兼容旧 session state**

旧 state 只有 `category` 时按映射恢复：`daily -> daily`、`exam -> study`、`movies -> culture`、`news_podcasts -> news`，子场景为 `None`。新 state 写 `top_scene` 和 `sub_scene`。

- [ ] **Step 5: 运行测试并提交**

Run: `.venv/bin/pytest tests/application/test_practice_engine.py tests/application/test_qt_controller.py -q`

Expected: PASS。

```bash
git add src/listening_cloze/domain/models.py src/listening_cloze/application/practice_engine.py tests/application/test_practice_engine.py tests/application/test_qt_controller.py
git commit -m "perf: keep practice queues bounded"
```

### Task 4: Controller 暴露场景目录和持久选择

**Files:**
- Modify: `src/listening_cloze/application/controller.py`
- Modify: `tests/application/test_qt_controller.py`

**Interfaces:**
- Produces QML properties: `sceneCatalog`, `selectedTopScene`, `selectedSubScene`, `sceneLabel`。
- Produces slots: `setScene(top_scene, sub_scene)`, `startQuantitative(top_scene, sub_scene, difficulty, count)`, `startEndless(top_scene, sub_scene)`。

- [ ] **Step 1: 写入 controller 失败测试**

```python
def test_controller_exposes_database_scene_catalog_and_persists_selection(controller) -> None:
    assert len(controller.sceneCatalog) == 8
    controller.setScene("travel", "travel_hotel")
    assert controller.selectedTopScene == "travel"
    assert controller.selectedSubScene == "travel_hotel"
    assert controller.sceneLabel == "出行旅行 / 酒店住宿"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv/bin/pytest tests/application/test_qt_controller.py -q`

Expected: FAIL，新属性和 slot 尚不存在。

- [ ] **Step 3: 实现 controller 属性**

`sceneCatalog` 结构固定为：

```python
[
    {"key": "travel", "label": "出行旅行", "children": [
        {"key": "travel_transport", "label": "交通通勤"},
        {"key": "travel_directions", "label": "问路导航"},
        {"key": "travel_hotel", "label": "酒店住宿"},
        {"key": "travel_tourism", "label": "旅行观光"},
    ]}
]
```

选择保存在 `selected_top_scene`、`selected_sub_scene` 设置键中；数据库中不存在的旧值回退到 `daily` 与 `None`。

- [ ] **Step 4: 运行测试并提交**

Run: `.venv/bin/pytest tests/application/test_qt_controller.py -q`

Expected: PASS。

```bash
git add src/listening_cloze/application/controller.py tests/application/test_qt_controller.py
git commit -m "feat: expose hierarchical scene selection"
```

### Task 5: 实现首页两级场景选择 UI

**Files:**
- Create: `src/listening_cloze/ui/qml/SceneSelector.qml`
- Modify: `src/listening_cloze/ui/qml/HomePage.qml`
- Modify: `src/listening_cloze/ui/qml/Main.qml`
- Create: `src/listening_cloze/ui/qml/qmldir`
- Modify: `tests/ui/test_qml_smoke.py`

**Interfaces:**
- Consumes: Task 4 的 `sceneCatalog` 和 `setScene()`。
- Produces: 8 个大类两行布局、4 个子场景与“全部该类”。

- [ ] **Step 1: 写入 QML 失败测试**

测试加载 HomePage 后查找 `topScene_daily`、`topScene_news`、`subScene_travel_hotel`、`allSubScenes`，点击后断言 controller 收到对应 key；在 `1024x700` 窗口断言开始按钮可见或可滚动到。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv/bin/pytest -m qt_serial tests/ui/test_qml_smoke.py -q`

Expected: FAIL，场景选择组件尚不存在。

- [ ] **Step 3: 实现 SceneSelector**

组件使用 `Flow` 渲染大类，四列两行；第二个 `Flow` 渲染“全部该类”和 4 个子场景。宽度不足时自然换行，外层 HomePage 现有 `Flickable` 承担纵向滚动。按钮 `objectName` 按 `topScene_<key>` 和 `subScene_<key>` 命名。

- [ ] **Step 4: 连接练习入口和页头**

定量、无尽模式均传递两个 scene key；Main/Practice 页头使用 controller `sceneLabel`。移除 QML 中旧的 4 类数组。

- [ ] **Step 5: 运行 UI 测试并提交**

Run: `.venv/bin/pytest -m qt_serial tests/ui/test_qml_smoke.py -q`

Expected: PASS。

```bash
git add src/listening_cloze/ui/qml/SceneSelector.qml src/listening_cloze/ui/qml/HomePage.qml src/listening_cloze/ui/qml/Main.qml src/listening_cloze/ui/qml/qmldir tests/ui/test_qml_smoke.py
git commit -m "feat: add hierarchical scene picker"
```

### Task 6: 应用端完整回归与性能门禁

**Files:**
- Create: `tests/performance/test_content_query_performance.py`

**Interfaces:**
- Consumes: Tasks 1-5。
- Produces: 90,000 题规模下的查询性能证据。

- [ ] **Step 1: 生成临时 90,000 题性能夹具**

测试使用事务批量插入 30,000 句和 90,000 版本，不依赖正式语料文件。

- [ ] **Step 2: 运行性能测试**

对 `sample_questions(limit=30)`、`get_questions_by_ids(30 ids)` 各运行 20 次，去掉第一次预热；两者中位数必须低于 200 ms，单次结果不得超过 1 秒。

Run: `.venv/bin/pytest tests/performance/test_content_query_performance.py -q`

Expected: PASS。

- [ ] **Step 3: 运行完整测试**

Run: `.venv/bin/pytest -n auto -m 'not qt_serial' -q`

Run: `.venv/bin/pytest -m qt_serial -q`

Run: `.venv/bin/ruff check .`

Run: `git diff --check`

Expected: 全部 0 退出码。

- [ ] **Step 4: 提交**

```bash
git add tests/performance/test_content_query_performance.py
git commit -m "test: gate large content query performance"
```
