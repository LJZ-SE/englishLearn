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
