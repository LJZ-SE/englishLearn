# 听写填空

面向 Windows 11 的完全离线英语听写填空应用。应用使用 Python、PySide6 与 Qt Quick/QML 开发，通过本地 TTS 播放完整英文句子，用户根据音频补全缺失的单词或短语。

当前需求和验收标准见 `docs/superpowers/specs/2026-07-22-listening-cloze-windows-design.md`。

## 开发命令

```bash
uv sync --locked --all-groups
uv run python tools/assets/fetch_supertonic3.py \
  --destination src/listening_cloze/data/supertonic-3
uv run python tools/run_tests.py
uv run python tools/run_app.py
```

模型固定为 Supertonic 3 revision `724fb5abbf5502583fb520898d45929e62f02c0b`，下载器会校验全部 17 个资产的 SHA-256。模型约 393 MB，不提交 Git；应用运行时不会联网或自动下载。

## 内容管线

内容库以可恢复的 SQLite 工作库驱动；按以下顺序执行各阶段。所有命令只接受本地来源文件和工作库路径，不记录或要求真实 API key。

```bash
# 1. 初始化可恢复工作库。
uv run listening-cloze-content init content-work.db

# 2. 从本地来源文件导入原始句子；按来源选择一个或多个 import-* 命令。
uv run listening-cloze-content import-tatoeba content-work.db data/tatoeba.tsv.bz2
uv run listening-cloze-content import-convokit content-work.db data/switchboard switchboard
uv run listening-cloze-content import-wikinews content-work.db data/wikinews.json
uv run listening-cloze-content import-gutenberg content-work.db data/1342.txt 1342

# 3. 清洗、近重复去除与场景分类；可重复运行以继续处理中断前的未完成条目。
uv run listening-cloze-content clean content-work.db
uv run listening-cloze-content dedupe content-work.db
uv run listening-cloze-content classify content-work.db

# 4. 按场景配额选择，并批量生成中文译文。
uv run listening-cloze-content select content-work.db
uv run listening-cloze-content translate content-work.db --batch-size 32

# 5. 导出翻译质量门禁未通过的条目，人工或受控 LLM 修正后导回。
uv run listening-cloze-content export-llm-repairs content-work.db repairs.jsonl
uv run listening-cloze-content import-llm-repairs content-work.db repaired.jsonl

# 6. 查看各阶段累计结果与拒绝条目数。
uv run listening-cloze-content status content-work.db
```

`translate` 使用固定版本的 OPUS-MT 英译中模型；首次实际翻译前应将该模型准备在本地缓存。管线测试使用 FakeTranslator，不会下载模型或访问网络。

## 已实现功能

- 300 个真实来源英文原句、900 道三档难度题，覆盖日常、考试、影视、新闻/播客。
- 单词与 2–4 词短语挖空，可见空位数严格等于规范答案单词数。
- 定量 10/20/30 题与无尽模式；无尽模式连续 5 题答对升级、连续 5 题答错降级。
- 首次答错后再次答对会欢呼，但本题成绩仍为错误。
- 本地 F3 女声 TTS、完整句子缓存、当前题及后两题后台预生成。
- SQLite 学习记录、未完成会话恢复、设置持久化、升级前备份和启动资产修复页。
- 音频失败自动重试，失败后可重新生成或无损跳过本题。

## Windows 安装包

项目使用 GitHub Actions 的 `windows-2025` Runner 构建，macOS 可直接触发：

```bash
uv run python packaging/windows_build.py trigger --ref main
uv run python packaging/windows_build.py latest --ref main --destination outputs/windows
```

工作流会重新下载并校验模型、运行全量测试、生成 PyInstaller onedir 应用、执行真实离线 TTS 冒烟检查，再用 Inno Setup 生成 `ListeningClozeSetup.exe`、`SHA256SUMS.txt` 和 `build-manifest.json`。

题库逐条归属和第三方许可见 `src/listening_cloze/data/sources.json` 与 `THIRD_PARTY_NOTICES.md`。
