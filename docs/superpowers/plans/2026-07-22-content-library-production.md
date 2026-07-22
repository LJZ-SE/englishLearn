# Content Library Production and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用已验证管线生产、翻译、审核并发布 30,000 句、90,000 题的正式离线题库。

**Architecture:** 所有长时间任务写入 `work/content-library/content-work.db` 并可恢复；LLM 修正通过版本化 JSONL 往返。只有精确配额和所有质量门禁通过后，才原子替换正式 `content.db`，随后重新打包和验证应用。

**Tech Stack:** Python 3.12、SQLite、OPUS-MT、Codex LLM、pytest、PyInstaller、PySide6。

## Global Constraints

- 正式库必须精确包含 30,000 句和 90,000 题。
- 每个子场景必须达到规格中的精确配额。
- 每个子场景必须由 LLM 抽检至少 100 句，总抽检至少 3,200 句。
- 旧 300 句题目 ID、用户进度和未完成任务必须可恢复。
- 旧 300 句必须作为受保护记录进入新配额，重新分类并重新生成中文翻译，不得被候选池选择淘汰。
- 发布失败不得破坏当前正式题库。
- 语料、模型缓存和工作库不得加入应用安装包。

---

### Task 1: 建立生产目录、冻结来源和采集候选池

**Files:**
- Create: `work/content-library/.gitkeep`
- Create: `work/content-library/source-lock.json`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Foundation plan 的 `listening-cloze-content` CLI。
- Produces: `work/content-library/content-work.db` 和冻结来源校验和。

- [ ] **Step 1: 配置工作目录忽略规则**

`.gitignore` 忽略 `work/content-library/*.db`、下载包、模型缓存、JSONL 批次输出，只保留 `.gitkeep` 和 `source-lock.json`。

- [ ] **Step 2: 初始化工作库**

Run: `.venv/bin/listening-cloze-content init work/content-library/content-work.db`

Expected: status 输出所有阶段为 0。

- [ ] **Step 3: 下载并导入固定来源**

Run: `.venv/bin/listening-cloze-content import-all work/content-library/content-work.db --manifest tools/content_pipeline/source_manifest.json --lock work/content-library/source-lock.json`

Expected: `raw` 计数至少 150,000；source lock 包含下载时间、最终 URL、文件大小和 SHA-256。

- [ ] **Step 4: 导入旧 300 句为受保护记录**

Run: `.venv/bin/listening-cloze-content import-legacy src/listening_cloze/data/content.db work/content-library/content-work.db --protected`

Expected: 精确导入 300 个不同的规范化句子；每条保留原 sentence/question ID 和 alias 映射，`source_name=legacy-content`、`protected=1`，中文翻译不直接沿用而进入后续重译阶段。

- [ ] **Step 5: 验证来源与许可溯源**

Run: `.venv/bin/listening-cloze-content report-sources work/content-library/content-work.db --output work/content-library/source-report.json`

Expected: 至少 4 种来源类型；报告中不存在空 `source_name`、`source_item_id`、`license_name` 或 `license_url`。

- [ ] **Step 6: 提交非生成文件**

```bash
git add .gitignore work/content-library/.gitkeep work/content-library/source-lock.json
git commit -m "chore: lock content production sources"
```

### Task 2: 清洗、去重、分类和精确配额选择

**Files:**
- Generated: `work/content-library/classification-repairs.jsonl`

**Interfaces:**
- Produces: 工作库中精确 30,000 个 `selected` 记录。

- [ ] **Step 1: 执行清洗与安全过滤**

Run: `.venv/bin/listening-cloze-content clean work/content-library/content-work.db --batch-size 2000`

Expected: 命令可重复运行；第二次运行处理数量为 0。

- [ ] **Step 2: 执行近似去重**

Run: `.venv/bin/listening-cloze-content dedupe work/content-library/content-work.db --batch-size 5000`

Expected: 完成后重复运行处理数量为 0，报告包含 exact 和 near duplicate 数量。

- [ ] **Step 3: 执行层级分类并导出低置信度项**

Run: `.venv/bin/listening-cloze-content classify work/content-library/content-work.db --batch-size 2000 --export-llm work/content-library/classification-repairs.jsonl`

Expected: JSONL 只包含 `method=llm_required` 的记录，并带 32 个合法候选标签说明。

- [ ] **Step 4: 使用 Codex LLM 分批修正分类并导入**

每批最多 500 条，输出 `classification-repairs-0001.result.jsonl` 一类文件；每行只允许 `item_id`、`top_scene`、`sub_scene`、`reason`。导入命令：

Run: `.venv/bin/listening-cloze-content import-classifications work/content-library/content-work.db work/content-library/classification-repairs-*.result.jsonl`

Expected: 所有 key 均存在于 `SCENES`，低置信度待处理数为 0。

- [ ] **Step 5: 执行精确配额选择**

Run: `.venv/bin/listening-cloze-content select work/content-library/content-work.db --exact-quotas`

Expected: 输出 32 个子场景精确配额，总计 30,000；300 条 `protected` 记录全部在 selected 集合中；不足或受保护记录造成集中度冲突时命令失败且不产生 selected 标记。

### Task 3: 翻译、自动修正与 3,200 句 LLM 抽检

**Files:**
- Generated: `work/content-library/translation-repairs.jsonl`
- Generated: `work/content-library/translation-audit.jsonl`
- Generated: `work/content-library/translation-audit-results.jsonl`

**Interfaces:**
- Produces: 30,000 条通过质量校验的 `translation_zh`。

- [ ] **Step 1: 执行 OPUS-MT 初译**

Run: `.venv/bin/listening-cloze-content translate work/content-library/content-work.db --model Helsinki-NLP/opus-mt-en-zh --batch-size 32`

Expected: 可中断恢复；完成后 translated 计数为 30,000。

- [ ] **Step 2: 导出并修正自动校验异常项**

Run: `.venv/bin/listening-cloze-content export-llm-repairs work/content-library/content-work.db work/content-library/translation-repairs.jsonl`

使用 Codex LLM 每批最多 300 条生成结果，然后运行：

Run: `.venv/bin/listening-cloze-content import-llm-repairs work/content-library/content-work.db work/content-library/translation-repairs-*.result.jsonl`

Expected: translation issue 计数为 0。

- [ ] **Step 3: 生成分层随机抽检集**

Run: `.venv/bin/listening-cloze-content export-translation-audit work/content-library/content-work.db work/content-library/translation-audit.jsonl --per-scene 100 --seed 20260722`

Expected: 恰好 3,200 条，每个子场景 100 条。

- [ ] **Step 4: 使用 Codex LLM 审核并导入结果**

LLM 每行输出：

```json
{"item_id":42,"status":"pass","replacement":"","issues":[],"review_note":"含义、数字和语气一致"}
```

需要修正时 `status=replace` 且 `replacement` 非空。导入：

Run: `.venv/bin/listening-cloze-content import-translation-audit work/content-library/content-work.db work/content-library/translation-audit-results.jsonl`

Expected: 3,200 条都有审核结果，replacement 重新通过自动校验。

- [ ] **Step 5: 重新检查同源系统性问题**

Run: `.venv/bin/listening-cloze-content translation-report work/content-library/content-work.db --output work/content-library/translation-report.json`

Expected: 按 issue、来源、场景统计；任何单一 issue 在抽检中超过 2% 时命令返回非零，必须扩大对应规则的 LLM 修正范围后重跑。

### Task 4: 生成三个难度版本并发布候选数据库

**Files:**
- Generated: `work/content-library/content-v2.candidate.db`
- Generated: `work/content-library/quality-report.json`
- Generated: `work/content-library/sources.json`

**Interfaces:**
- Consumes: 30,000 条已分类、已翻译记录。
- Produces: schema v2 候选数据库。

- [ ] **Step 1: 生成三个题目版本**

Run: `.venv/bin/listening-cloze-content generate-variants work/content-library/content-work.db --batch-size 2000`

Expected: variant 计数为 90,000；失败项必须回到 selection 补位，重新翻译补位句并再次生成，直到 32 个场景仍满足精确配额。

- [ ] **Step 2: 构建候选数据库**

Run: `.venv/bin/listening-cloze-content build work/content-library/content-work.db work/content-library/content-v2.candidate.db --preserve-ids-from src/listening_cloze/data/content.db --report work/content-library/quality-report.json --sources work/content-library/sources.json`

Expected: 候选库为 schema version 2，旧 300 句及题目 ID 均存在。

- [ ] **Step 3: 运行 SQLite 与数据门禁**

Run: `.venv/bin/listening-cloze-content validate work/content-library/content-v2.candidate.db --report work/content-library/quality-report.json`

Expected: `PRAGMA integrity_check` 为 `ok`；30,000 句、90,000 题、32 个精确配额、三个难度各 30,000；旧 300 句及其 ID/alias 全部存在；空翻译、空许可、精确重复、近似重复和答案区间错误均为 0；每个子场景的单一来源占比不超过 45%，非空单一作者占比不超过 8%。

- [ ] **Step 4: 运行发布数据测试**

Run: `LISTENING_CLOZE_CONTENT_DB=work/content-library/content-v2.candidate.db .venv/bin/pytest tests/content_pipeline/test_release_data.py tests/performance/test_content_query_performance.py -q`

Expected: PASS。

### Task 5: 原子发布、应用回归和打包验证

**Files:**
- Replace after gates: `src/listening_cloze/data/content.db`
- Replace after gates: `src/listening_cloze/data/quality-report.json`
- Replace after gates: `src/listening_cloze/data/sources.json`

**Interfaces:**
- Consumes: Task 4 候选库与报告。
- Produces: 正式 3 万句离线应用。

- [ ] **Step 1: 创建旧正式库校验和并原子发布**

Run: `.venv/bin/listening-cloze-content publish work/content-library/content-v2.candidate.db src/listening_cloze/data/content.db --report work/content-library/quality-report.json --report-target src/listening_cloze/data/quality-report.json --sources work/content-library/sources.json --sources-target src/listening_cloze/data/sources.json`

Expected: publish 先备份旧文件到 `work/content-library/release-backup/`，再使用同目录临时文件原子替换；任何复制失败恢复旧文件。

- [ ] **Step 2: 运行完整测试和静态检查**

Run: `.venv/bin/pytest -n auto -m 'not qt_serial' -q`

Run: `.venv/bin/pytest -m qt_serial -q`

Run: `.venv/bin/ruff check .`

Run: `git diff --check`

Expected: 全部 0 退出码。

- [ ] **Step 3: 打包 macOS 验证版**

Run: `.venv/bin/pyinstaller --noconfirm --clean --distpath /private/tmp/listening-cloze-30k-dist --workpath /private/tmp/listening-cloze-30k-build packaging/listening_cloze.spec`

Run: `env LISTENING_CLOZE_DATA_DIR=/private/tmp/listening-cloze-30k-smoke /private/tmp/listening-cloze-30k-dist/ListeningCloze/ListeningCloze --smoke-test`

Expected: 构建和冒烟测试退出码均为 0。

- [ ] **Step 4: 手动验收核心流程**

在 macOS 验证版逐项检查：8 个大类、每类 4 个子场景、全部场景、10/20/30 题定量模式、无尽模式、返回主页继续任务、设置返回原页、自动播放、Command+R 重播、中文翻译和 TTS 后两题预取。

- [ ] **Step 5: 提交正式题库与报告**

```bash
git add src/listening_cloze/data/content.db src/listening_cloze/data/quality-report.json src/listening_cloze/data/sources.json
git commit -m "data: expand offline library to 30000 sentences"
```

- [ ] **Step 6: 记录最终验收证据**

最终交付必须报告：句子数、题目数、32 个场景配额、翻译修正数、LLM 抽检数、数据库大小、全套测试数量、打包路径和当前运行进程。不得只报告“构建成功”。
