# Content Pipeline Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可断点续跑、可扩展到 15 万候选和 3 万成品的题库生产管线。

**Architecture:** 使用独立 SQLite 工作库保存采集、清洗、分类、去重、翻译和修正状态；场景目录、配额和质量门禁集中定义。正式 `content.db` 在本计划中不替换，只产出通过阶段检查的候选工作库。

**Tech Stack:** Python 3.12、SQLite、NumPy、pytest、wordfreq、spaCy、Transformers 4.x、PyTorch、SentencePiece。

## Global Constraints

- 最终目标为 30,000 个不同英文句子和 90,000 个难度版本。
- 场景必须为 8 个大类、32 个子场景，并采用规格中的精确配额。
- 英文句子必须包含 5 至 35 个英文单词。
- 内容必须排除色情、粗口、自残、仇恨、极端暴力和明显冒犯内容。
- 中文翻译必须由 OPUS-MT 初译，异常项由 LLM 修正。
- 构建过程必须支持断点续跑，已完成阶段不得重复调用模型。
- 本计划不得覆盖 `src/listening_cloze/data/content.db`。

---

### Task 1: 集中定义场景目录与配额

**Files:**
- Create: `tools/content_pipeline/scenes.py`
- Create: `tests/content_pipeline/test_scenes.py`
- Modify: `tools/content_pipeline/models.py`

**Interfaces:**
- Produces: `SceneDefinition`, `SCENES`, `TOP_SCENES`, `SUB_SCENES`, `TOTAL_SENTENCE_QUOTA`, `scene_by_key()`。
- Produces: `CollectedSentence.source_item_id: str`, `top_scene: str | None`, `sub_scene: str | None`。

- [ ] **Step 1: 写入场景目录失败测试**

```python
from tools.content_pipeline.scenes import SCENES, TOTAL_SENTENCE_QUOTA, scene_by_key


def test_scene_catalog_contains_exact_confirmed_hierarchy_and_quota() -> None:
    assert len({scene.top_key for scene in SCENES}) == 8
    assert len(SCENES) == 32
    assert TOTAL_SENTENCE_QUOTA == 30_000
    assert sum(scene.quota for scene in SCENES) == 30_000
    assert scene_by_key("daily_social").quota == 1_800
    assert scene_by_key("travel_hotel").top_key == "travel"
    assert scene_by_key("news_environment").label == "环境社会"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv/bin/pytest tests/content_pipeline/test_scenes.py -q`

Expected: FAIL，`tools.content_pipeline.scenes` 尚不存在。

- [ ] **Step 3: 实现场景目录**

```python
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
)
```

同时在同一文件派生 `TOP_SCENES`、`SUB_SCENES` 和 `TOTAL_SENTENCE_QUOTA`，不得复制第二份配额常量。

- [ ] **Step 4: 扩展采集模型并运行测试**

为 `CollectedSentence` 增加有默认值的新字段，保证现有调用方兼容：

```python
source_item_id: str = ""
top_scene: str | None = None
sub_scene: str | None = None
```

Run: `.venv/bin/pytest tests/content_pipeline/test_scenes.py tests/content_pipeline/test_pipeline.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add tools/content_pipeline/scenes.py tools/content_pipeline/models.py tests/content_pipeline/test_scenes.py
git commit -m "feat: define hierarchical content scenes"
```

### Task 2: 建立断点式 SQLite 工作库

**Files:**
- Create: `tools/content_pipeline/work_database.py`
- Create: `tests/content_pipeline/test_work_database.py`
- Create: `tools/content_pipeline/cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `WorkDatabase.initialize()`, `upsert_raw()`, `claim_batch()`, `mark_stage()`, `record_rejection()`, `stage_counts()`。
- Produces: CLI `listening-cloze-content init|status`。

- [ ] **Step 1: 写入工作库失败测试**

```python
from tools.content_pipeline.work_database import WorkDatabase


def test_work_database_is_idempotent_and_resumes_pending_rows(tmp_path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first_id = database.upsert_raw(
        source_name="Tatoeba",
        source_item_id="42",
        source_url="https://tatoeba.org/en/sentences/show/42",
        source_author="alice",
        license_name="CC BY 2.0 FR",
        license_url="https://creativecommons.org/licenses/by/2.0/fr/",
        text="The train arrives at nine o'clock.",
    )
    second_id = database.upsert_raw(
        source_name="Tatoeba",
        source_item_id="42",
        source_url="https://tatoeba.org/en/sentences/show/42",
        source_author="alice",
        license_name="CC BY 2.0 FR",
        license_url="https://creativecommons.org/licenses/by/2.0/fr/",
        text="The train arrives at nine o'clock.",
    )
    assert first_id == second_id
    assert database.claim_batch("dedupe", limit=10) == []
    batch = database.claim_batch("clean", limit=10)
    assert [row.id for row in batch] == [first_id]
    database.mark_stage(first_id, "clean", payload={"clean_text": "The train arrives."})
    assert database.claim_batch("clean", limit=10) == []
    assert [row.id for row in database.claim_batch("dedupe", limit=10)] == [first_id]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv/bin/pytest tests/content_pipeline/test_work_database.py -q`

Expected: FAIL，工作库模块尚不存在。

- [ ] **Step 3: 实现工作库结构和事务 API**

`initialize()` 执行以下完整结构；`raw_items` 使用 `(source_name, source_item_id)` 唯一约束：

```sql
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS raw_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_item_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_author TEXT NOT NULL,
    license_name TEXT NOT NULL,
    license_url TEXT NOT NULL,
    text TEXT NOT NULL,
    protected INTEGER NOT NULL DEFAULT 0 CHECK(protected IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE(source_name, source_item_id)
);
CREATE TABLE IF NOT EXISTS stage_results(
    item_id INTEGER NOT NULL REFERENCES raw_items(id),
    stage TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    model_version TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY(item_id, stage)
);
CREATE TABLE IF NOT EXISTS rejections(
    item_id INTEGER PRIMARY KEY REFERENCES raw_items(id),
    stage TEXT NOT NULL,
    reason TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS build_runs(
    id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running','passed','failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_stage_results_stage ON stage_results(stage, item_id);
CREATE INDEX IF NOT EXISTS idx_rejections_stage ON rejections(stage, item_id);
```

`upsert_raw()` 使用 `INSERT ... ON CONFLICT(source_name, source_item_id) DO UPDATE` 后按唯一键返回 ID。阶段前置关系固定为 `clean -> dedupe -> classify -> select -> translate -> variants`。`claim_batch(stage, limit)` 必须要求前置阶段已成功；`clean` 是唯一没有前置阶段的例外。其他阶段使用下列参数化查询，并把行映射为 `WorkItem` dataclass：

```sql
SELECT r.id, r.source_name, r.source_item_id, r.source_url, r.source_author,
       r.license_name, r.license_url, r.text, r.protected
FROM raw_items AS r
LEFT JOIN stage_results AS s ON s.item_id = r.id AND s.stage = :stage
JOIN stage_results AS p ON p.item_id = r.id AND p.stage = :previous_stage
LEFT JOIN rejections AS x ON x.item_id = r.id
WHERE s.item_id IS NULL AND x.item_id IS NULL
ORDER BY r.id
LIMIT :limit;
```

`mark_stage()` 使用 `(item_id, stage)` upsert JSON payload；`record_rejection()` 使用 `item_id` upsert；`stage_counts()` 按 stage 聚合并额外返回 raw 和 rejected 总数。

- [ ] **Step 4: 增加 CLI 并验证重复初始化**

在 `pyproject.toml` 增加：

```toml
[project.scripts]
listening-cloze = "listening_cloze.__main__:main"
listening-cloze-content = "tools.content_pipeline.cli:main"
```

CLI 的 `init WORK_DB` 调用 `initialize()`，`status WORK_DB` 输出 JSON 阶段计数。

Run: `.venv/bin/pytest tests/content_pipeline/test_work_database.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add tools/content_pipeline/work_database.py tools/content_pipeline/cli.py tests/content_pipeline/test_work_database.py pyproject.toml
git commit -m "feat: add resumable content work database"
```

### Task 3: 实现多来源采集与统一清洗

**Files:**
- Create: `tools/content_pipeline/convokit_source.py`
- Create: `tools/content_pipeline/gutenberg.py`
- Create: `tools/content_pipeline/source_manifest.json`
- Create: `tests/content_pipeline/test_sources.py`
- Modify: `tools/content_pipeline/tatoeba.py`
- Modify: `tools/content_pipeline/wikinews.py`
- Modify: `tools/content_pipeline/clean.py`
- Modify: `tools/content_pipeline/cli.py`

**Interfaces:**
- Produces: `iter_convokit_utterances(path, source_name)`, `iter_gutenberg_text(path, ebook_id)`。
- Produces: CLI `import-tatoeba`, `import-convokit`, `import-wikinews`, `import-gutenberg`, `clean`。

- [ ] **Step 1: 写入采集与清洗失败测试**

```python
def test_clean_rejects_subtitle_metadata_and_accepts_complete_dialogue() -> None:
    assert rejection_reason("00:01:14,000 --> 00:01:17,000") == "subtitle_metadata"
    assert rejection_reason("[Door slams]") == "stage_direction"
    assert rejection_reason("SPEAKER 2: We need to leave now.") == "speaker_label"
    assert rejection_reason("We need to leave before the last train.") is None
```

增加 ConvoKit JSONL 和 Gutenberg 文本夹具，断言输出包含稳定的 `source_item_id`、作者和原始地址。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv/bin/pytest tests/content_pipeline/test_sources.py tests/content_pipeline/test_pipeline.py -q`

Expected: FAIL，新采集器和拒绝原因尚不存在。

- [ ] **Step 3: 实现来源清单和采集器**

`source_manifest.json` 固定以下首批来源：

```json
[
  {"key":"tatoeba-eng","kind":"tatoeba","url":"https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences_detailed.tsv.bz2","license_name":"CC BY 2.0 FR","license_url":"https://creativecommons.org/licenses/by/2.0/fr/"},
  {"key":"cornell-movie-dialogs","kind":"convokit","download_name":"movie-corpus","license_name":"source terms","license_url":"https://convokit.cornell.edu/documentation/movie.html"},
  {"key":"switchboard","kind":"convokit","download_name":"switchboard-corpus","license_name":"source terms","license_url":"https://convokit.cornell.edu/documentation/switchboard.html"},
  {"key":"english-wikinews","kind":"wikinews","url":"https://en.wikinews.org/w/api.php","license_name":"per-item license","license_url":"https://en.wikinews.org/wiki/Wikinews:Copyright"},
  {"key":"gutenberg","kind":"gutenberg","ebook_ids":[11,74,76,84,98,1342,1661,2701,345,174],"license_name":"per-item terms","license_url":"https://www.gutenberg.org/policy/license.html"}
]
```

所有采集器只写工作库，不直接写正式数据库，并把来源名称、原始记录 ID、作者、许可名称和许可地址完整落库。ConvoKit 依赖只加入 `content` dependency group。

- [ ] **Step 4: 扩展清洗规则并运行测试**

清洗器先删除可安全移除的说话人前缀；纯时间码、纯舞台说明和清洗后不足 5 个或超过 35 个英文单词的记录写入明确拒绝原因。

Run: `.venv/bin/pytest tests/content_pipeline/test_sources.py tests/content_pipeline/test_pipeline.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add tools/content_pipeline/convokit_source.py tools/content_pipeline/gutenberg.py tools/content_pipeline/source_manifest.json tools/content_pipeline/tatoeba.py tools/content_pipeline/wikinews.py tools/content_pipeline/clean.py tools/content_pipeline/cli.py tests/content_pipeline/test_sources.py tests/content_pipeline/test_pipeline.py pyproject.toml
git commit -m "feat: collect and clean diverse sentence sources"
```

### Task 4: 实现可扩展近似去重、层级分类和配额选择

**Files:**
- Create: `tools/content_pipeline/dedupe.py`
- Create: `tests/content_pipeline/test_dedupe.py`
- Modify: `tools/content_pipeline/categorize.py`
- Modify: `tools/content_pipeline/selection.py`
- Modify: `tools/content_pipeline/cli.py`
- Test: `tests/content_pipeline/test_pipeline.py`

**Interfaces:**
- Produces: `simhash64(text) -> int`, `NearDuplicateIndex.add(text) -> bool`。
- Produces: `SceneClassification(top_scene, sub_scene, confidence, method)`。
- Produces: `select_scene_quotas(rows) -> dict[str, list[int]]`。

- [ ] **Step 1: 写入去重和分类失败测试**

```python
def test_simhash_index_only_rejects_near_duplicate_content() -> None:
    index = NearDuplicateIndex(threshold=0.76)
    assert index.add("The train leaves the station at nine o'clock.") is True
    assert index.add("The train leaves this station at nine o'clock.") is False
    assert index.add("Please send the revised report before Friday.") is True


def test_hierarchical_classifier_returns_fixed_scene_keys() -> None:
    result = SceneClassifier().classify("Could I reserve a double room for two nights?")
    assert result.top_scene == "travel"
    assert result.sub_scene == "travel_hotel"
    assert 0.0 <= result.confidence <= 1.0


def test_quota_selection_limits_source_and_author_concentration() -> None:
    selected = select_scene_quotas(fixture_rows())
    for rows in selected.values():
        assert max_source_share(rows) <= 0.45
        assert max_known_author_share(rows) <= 0.08


def test_quota_selection_always_retains_protected_legacy_rows() -> None:
    rows = fixture_rows_with_protected_legacy_items()
    selected_ids = {item.id for items in select_scene_quotas(rows).values() for item in items}
    assert protected_ids(rows) <= selected_ids
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv/bin/pytest tests/content_pipeline/test_dedupe.py tests/content_pipeline/test_pipeline.py -q`

Expected: FAIL，SimHash 索引和层级分类尚不存在。

- [ ] **Step 3: 实现 SimHash 分桶**

使用规范化内容词的 3-gram 计算 64 位 SimHash，将 64 位拆成 4 个 16 位 band。只有共享 band 的文本才运行现有 Jaccard 精确比较；`add()` 返回 `False` 时同时提供命中的规范化哈希用于报告。

- [ ] **Step 4: 实现层级分类和低置信度队列**

分类器必须先接受来源显式场景，再使用固定关键词权重。最高分低于 `2.0` 或第一、第二名差值低于 `0.75` 时，将 `method` 标为 `llm_required`，而不是强行归类。

- [ ] **Step 5: 实现配额选择**

`select_scene_quotas()` 按 `SCENES` 精确配额选择，先锁定已映射到合法场景的 `protected=1` 旧题，再用规范化哈希作稳定排序补齐剩余名额；每个子场景中单一来源不得超过 45%，非空单一作者不得超过 8%。受保护记录也计入集中度；若其自身造成门禁冲突则明确失败，不得静默删除。任何缺口抛出包含 32 个场景差额的 `SceneQuotaError`。

Run: `.venv/bin/pytest tests/content_pipeline/test_dedupe.py tests/content_pipeline/test_pipeline.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add tools/content_pipeline/dedupe.py tools/content_pipeline/categorize.py tools/content_pipeline/selection.py tools/content_pipeline/cli.py tests/content_pipeline/test_dedupe.py tests/content_pipeline/test_pipeline.py
git commit -m "feat: scale deduplication and scene classification"
```

### Task 5: 实现 OPUS-MT 翻译、自动校验和 LLM 修正交换格式

**Files:**
- Create: `tools/content_pipeline/translation.py`
- Create: `tests/content_pipeline/test_translation.py`
- Modify: `tools/content_pipeline/work_database.py`
- Modify: `tools/content_pipeline/cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `Translator.translate_batch(texts) -> list[str]`。
- Produces: `validate_translation(source, translation) -> tuple[str, ...]`。
- Produces: CLI `translate`, `export-llm-repairs`, `import-llm-repairs`。

- [ ] **Step 1: 写入翻译失败测试**

```python
class FakeTranslator:
    model_version = "fake-1"
    def translate_batch(self, texts: list[str]) -> list[str]:
        return ["火车九点到达。" for _ in texts]


def test_translation_stage_checkpoints_success_and_flags_number_loss(tmp_path) -> None:
    assert validate_translation("The train arrives at 9:30.", "火车到达。") == (
        "number_mismatch",
    )
    assert validate_translation("The train arrives at nine.", "火车九点到达。") == ()
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv/bin/pytest tests/content_pipeline/test_translation.py -q`

Expected: FAIL，翻译模块尚不存在。

- [ ] **Step 3: 增加仅构建环境使用的依赖**

```toml
content = [
    "beautifulsoup4>=4.13,<5",
    "convokit>=4.1,<5",
    "httpx>=0.28,<1",
    "sentencepiece>=0.2,<1",
    "spacy>=3.8,<4",
    "torch>=2.6,<3",
    "transformers>=4.50,<5",
    "wordfreq>=3.1,<4",
]
```

这些依赖不得加入 `[project].dependencies`，防止进入应用安装包。

Run: `uv sync --group content --group dev`

Expected: `uv.lock` 更新成功，应用基础依赖分组不包含 torch、transformers 或 convokit。

- [ ] **Step 4: 实现 OPUS-MT 批量翻译和质量校验**

`OpusMtTranslator` 固定模型 `Helsinki-NLP/opus-mt-en-zh`，默认批次 32。质量校验必须覆盖空译、中文比例、数字/金额/百分比、明显英文残留和异常长度。每批成功后立即写工作库，并保存模型 revision。

- [ ] **Step 5: 实现 LLM JSONL 交换格式**

导出格式必须为一行一个对象：

```json
{"item_id":42,"source":"The train arrives at 9:30.","draft":"火车到达。","issues":["number_mismatch"],"top_scene":"travel","sub_scene":"travel_transport"}
```

导入格式必须包含同一 `item_id`、`translation_zh` 和 `review_note`；导入时重新运行自动校验，仍失败的记录不得标记完成。

- [ ] **Step 6: 运行测试并提交**

Run: `.venv/bin/pytest tests/content_pipeline/test_translation.py tests/content_pipeline/test_work_database.py -q`

Expected: PASS。

```bash
git add tools/content_pipeline/translation.py tools/content_pipeline/work_database.py tools/content_pipeline/cli.py tests/content_pipeline/test_translation.py pyproject.toml uv.lock
git commit -m "feat: add resumable automatic translation pipeline"
```

### Task 6: 基础管线完整验证

**Files:**
- Create: `tests/content_pipeline/test_pipeline_e2e.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1-5 的 CLI 和工作库。
- Produces: 一份使用缩小配额的可重复端到端构建记录。

- [ ] **Step 1: 增加微型端到端测试**

在 `tests/content_pipeline/test_pipeline_e2e.py` 使用 32 个子场景各 3 句、FakeTranslator 和临时工作库，按采集、清洗、去重、分类、选择、翻译顺序跑完整链路，断言 96 句全部带场景和译文。

- [ ] **Step 2: 运行内容管线测试**

Run: `.venv/bin/pytest -n auto tests/content_pipeline -q`

Expected: 全部 PASS。

- [ ] **Step 3: 更新 README 命令**

README 必须记录以下顺序和含义：`init`、`import-*`、`clean`、`dedupe`、`classify`、`select`、`translate`、`export-llm-repairs`、`import-llm-repairs`、`status`。不得记录真实 API key。

- [ ] **Step 4: 运行静态检查并提交**

Run: `.venv/bin/ruff check .`

Run: `git diff --check`

Expected: 均为 0 退出码。

```bash
git add README.md tests/content_pipeline/test_pipeline_e2e.py
git commit -m "test: verify resumable content pipeline end to end"
```
