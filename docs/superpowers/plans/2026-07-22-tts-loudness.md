# TTS Loudness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将离线 TTS 音频统一到用户确认的 `-11 dBFS` 平均响度，并使用 `-1 dBFS` 柔和峰值保护。

**Architecture:** 在 `SupertonicBackend` 保存 WAV 前完成 RMS 归一化和柔和限幅；目标值由 `AudioProfile` 传入，并通过现有 profile 哈希机制自动使旧缓存失效。

**Tech Stack:** Python 3.12、NumPy、pytest、PyInstaller、PySide6。

## Global Constraints

- 目标平均响度必须为 `-11 dBFS`。
- 柔和限幅上限必须为 `-1 dBFS`。
- 不得修改用户的题目进度和设置数据。
- 新题仍按现有预取与缓存流程生成音频。

---

### Task 1: 音频响度处理与缓存配置

**Files:**
- Modify: `src/listening_cloze/infrastructure/supertonic_backend.py`
- Modify: `src/listening_cloze/infrastructure/audio_cache.py`
- Modify: `src/listening_cloze/application/bootstrap.py`
- Test: `tests/infrastructure/test_supertonic_backend.py`
- Test: `tests/infrastructure/test_audio_cache.py`

**Interfaces:**
- Consumes: Supertonic 生成的 NumPy 波形和 `AudioProfile`。
- Produces: `SupertonicBackend._normalize_loudness(waveform)`，输出经过 RMS 归一化与柔和限幅的波形。

- [ ] **Step 1: 写入失败测试**

增加测试，断言普通波形输出 RMS 为 `-11 dBFS ±0.05 dB`、峰值不超过 `-1 dBFS`、静音保持不变，并断言目标响度变化会改变缓存路径。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv/bin/pytest tests/infrastructure/test_supertonic_backend.py tests/infrastructure/test_audio_cache.py -q`

Expected: 新响度断言失败，因为现有实现仍使用固定 `5 dB` 增益。

- [ ] **Step 3: 实现最小修改**

将固定增益替换为 `target_rms_dbfs=-11.0` 和 `peak_ceiling_dbfs=-1.0`。非静音波形通过二分搜索求增益，再使用 `tanh` 柔和限幅；配置通过 bootstrap 传入后端。

- [ ] **Step 4: 运行目标测试并确认 GREEN**

Run: `.venv/bin/pytest tests/infrastructure/test_supertonic_backend.py tests/infrastructure/test_audio_cache.py -q`

Expected: 目标测试全部通过。

- [ ] **Step 5: 运行完整验证**

Run: `.venv/bin/pytest -n auto -m 'not qt_serial' -q`

Run: `.venv/bin/pytest -m qt_serial -q`

Run: `.venv/bin/ruff check .`

Run: `git diff --check`

Expected: 所有测试和静态检查通过。

### Task 2: 打包并启动 macOS 验证版

**Files:**
- Read: `packaging/listening_cloze.spec`

**Interfaces:**
- Consumes: Task 1 中通过验证的源代码。
- Produces: 可在当前 Mac 运行的新版 `ListeningCloze` 应用。

- [ ] **Step 1: 使用 PyInstaller 构建新版本**

Run: `.venv/bin/pyinstaller --noconfirm --clean --distpath /private/tmp/listening-cloze-volume-v8-dist --workpath /private/tmp/listening-cloze-volume-v8-build packaging/listening_cloze.spec`

Expected: 构建退出码为 0。

- [ ] **Step 2: 运行打包应用冒烟测试**

Run: `env LISTENING_CLOZE_DATA_DIR=/private/tmp/listening-cloze-volume-v8-smoke /private/tmp/listening-cloze-volume-v8-dist/ListeningCloze/ListeningCloze --smoke-test`

Expected: 冒烟测试退出码为 0。

- [ ] **Step 3: 启动验证版**

使用 `/private/tmp/listening-cloze-manual-test` 作为数据目录启动新版本，确认进程保持运行。新 profile 会使旧的低响度缓存自动失效。
