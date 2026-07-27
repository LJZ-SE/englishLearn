# Design QA — 学习中心与专注练习台

## 验收基准

### 学习中心首页

- 视觉基准：`docs/design/learning-dashboard-prototype.png`
- 标准窗口：`docs/design/qa/listening-dashboard-final5-1536x1024.png`
- 紧凑窗口：`docs/design/qa/listening-dashboard-final5-960x700.png`
- 标准窗口对照：`docs/design/qa/listening-dashboard-final5-combined.png`
- 核心练习区对照：`docs/design/qa/listening-dashboard-final5-practice-comparison.png`
- 非四六级场景筛选：`docs/design/qa/listening-dashboard-scene-visibility-final-1536x1024.png`

### 专注练习台

- 视觉真值：`docs/design/listening-practice-prototype.png`
- 实现截图：`docs/design/qa/listening-practice-implemented-final-1536x1024.png`
- 归一化原型：`docs/design/qa/listening-practice-reference-final-1536x976.png`
- 归一化实现：`docs/design/qa/listening-practice-implemented-final-1536x976.png`
- 全屏对照与 50% 叠图：`docs/design/qa/listening-practice-comparison-final.png`
- 音频区对照：`docs/design/qa/listening-practice-focus-audio.png`
- 句子和操作区对照：`docs/design/qa/listening-practice-focus-answer-actions.png`
- 进度区对照：`docs/design/qa/listening-practice-focus-progress.png`
- 紧凑窗口：`docs/design/qa/listening-practice-compact-final-960x700.png`
- 长句首屏：`docs/design/qa/listening-practice-long-final-1536x1024.png`
- 长句紧凑窗口：`docs/design/qa/listening-practice-long-compact-final-960x700.png`
- 音频工作台原型：`docs/design/listening-practice-audio-workbench-prototype.png`
- 音频工作台实现：`docs/design/qa/listening-practice-audio-workbench-final-1536x1024.png`
- 音频工作台长句：`docs/design/qa/listening-practice-audio-workbench-long-final-1536x1024.png`
- 音频工作台紧凑窗口：`docs/design/qa/listening-practice-audio-workbench-compact-final-960x700.png`
- 音频工作台重点对照：`docs/design/qa/listening-practice-audio-workbench-focus-comparison.png`
- 重听按钮对齐：`docs/design/qa/listening-practice-replay-alignment-final-1536x1024.png`

## 视口、密度和状态

- 原型像素：1536 × 1024，包含 48 px 的 macOS 标题栏。
- 实现像素：1536 × 1024，QQuickWindow 客户区，设备像素比 1。
- 1:1 比较：裁去原型标题栏，并裁取实现前 976 px，双方均为 1536 × 976；没有缩放后再判断像素位置。
- 紧凑验证：960 × 700，侧栏收窄，主内容独立纵向滚动，底部进度固定。
- 状态：资源完整、日常口语、简单、定量 10 题、第 4 题、前三题正确、当前题未作答、第一个空位选中。
- 长句状态：资源完整、困难、定量 10 题、第 1 题、当前题未作答；使用 164 字符英文句子验证首屏布局。
- 数据：截图通过临时 SQLite 用户库、正式 `PracticeEngine`、`PracticeController` 和正式 QML 页面构造，没有预览专用页面或假业务状态。

## 最终检查

### 字体与排版

- 标题、句子、按钮、说明和进度使用 `AppTheme.fontFamily` 的平台字体；macOS 为 `Hiragino Sans GB`，Windows 为 `Segoe UI`。
- 卡片标题 26 px、英文句子 28 px 半粗体、按钮和辅助文案层级与原型一致。
- 两个答案框保持逐词对应，短句单行居中，长句通过 `Flow` 按文本和输入框整体换行。
- 固定文案与原型一致；题目、翻译、答案、场景、难度和计数来自正式业务字段。

### 间距与布局

- 标准视口中的 248 px 侧栏、88 px 顶栏、24 px 页面边距、16 px 卡片圆角、804 px 主卡高度和 130 px 进度区与原型对齐。
- 播放按钮、波形、重听和语速、吉祥物、句子、操作按钮及进度标记的视觉顺序和分组与原型一致。
- 音频控制改为一个浅蓝播放器面板：播放按钮与波形位于主轨道，重听和三档语速收纳到波形下方；右侧教练区缩小并独立，避免四个控件横向散落。
- 重听按钮使用统一中心线的 `RowLayout`；刷新图标和“重听”文字的几何中心差不超过 1 px。
- 长句自动启用紧凑纵向节奏，保留 28 px 句子字号，压缩音频区、卡片内边距和非核心留白；1536 × 1024 下无需滚动即可看到三项操作和快捷键提示。
- 960 × 700 下吉祥物和离线徽章按需收纳，内容区可滚动到操作按钮；进度区不会覆盖或拦截操作。
- 未发现重叠、水平溢出、不可达按钮或绑定循环。

### 颜色与视觉令牌

- 背景、侧栏、卡片、主色、选中态、成功、错误、边框和输入框焦点均来自统一主题令牌。
- 主按钮、浅蓝选中态、绿色正确进度、红色结束本轮按钮和灰蓝辅助文本与原型语义一致。
- 对比度、焦点边框和至少 40 px 的主要点击目标满足桌面键鼠操作需要。

### 图像与图标

- Logo、戴耳机的闲置吉祥物、欢呼吉祥物和沮丧吉祥物均为真实 PNG 资源，不使用 QML 几何图形、文本符号或占位插图代替。
- 闲置吉祥物根据原型补齐耳机、挥手姿态和透明背景，标准视口中的主体、裁切和比例与原型一致。
- 导航、播放、刷新、设置和离线状态使用打包的 Material Icons 字体，风格统一且可离线使用。
- PNG 透明通道、边缘、缩放和高分辨率显示未发现明显锯齿、背景方格或遮罩接缝。

### 核心交互

- 新题自动播放；播放和重听前先停止当前 `SoundEffect`，不会叠加音频。
- 支持空格重听、输入框内空格跳到下一个单词、macOS `⌘R`、其他平台 `Ctrl+R` 和 Enter 检查/下一题。
- 显示中文只切换本地预览，不填答案、不改变结果、不写数据库；正确或查看答案后自动显示翻译。
- 四六级级别只在一级场景选中“四六级考试”后出现；日常口语、考试英语及其他场景仅显示各自内容分类。
- 第一次答错后再次答对会显示正确反馈，但统计仍保留待掌握。
- 返回主页保留未完成任务；设置关闭回到来源页面。
- 波形宽度按句长缩放；TTS 继续缓存当前题和后两题。
- 正确、错误、查看答案、音频错误、长句、多词短语和紧凑滚动状态均有自动化覆盖。

## 比较历史

1. 首页首轮发现练习配置横向挤压和重复入口，判定为 P1；改为纵向配置并合并入口。
2. 首页第二轮发现扩展场景占用核心空间和侧栏吉祥物风格偏差，判定为 P2；改为下拉收纳并使用位图资源。
3. 首页第三轮发现平台字体回退警告，判定为 P2；改为平台字体令牌。
4. 答题页首轮发现闲置吉祥物缺少原型中的耳机，判定为 P2；新增 `mascot-idle-headphones.png` 并在侧栏和答题反馈中复用。修复后证据见最终全屏和音频区对照。
5. 答题页首轮发现波形柱过粗、幅度层级不足，判定为 P2；改为按实际宽度计算细柱数量、4 px 间距和非线性幅度曲线。修复后证据见 `listening-practice-focus-audio.png`。
6. 答题页首轮发现快捷键只有纯文本，缺少原型中的键帽层级，判定为 P2；补齐 Space/Enter 键帽并保留平台快捷键逻辑。修复后证据见 `listening-practice-focus-answer-actions.png`。
7. 真实窗口验证发现长句会把核心操作推到首屏之外，判定为 P1；新增按句长触发的紧凑布局，并用同一句长句加入无滚动可见性回归测试。修复证据见 `listening-practice-long-final-1536x1024.png`。
8. 用户复核发现音频区播放、波形、重听、语速和吉祥物彼此分散，判定为 P2；按确认的音频工作台原型改为一体播放器面板和独立教练区。修复证据见 `listening-practice-audio-workbench-focus-comparison.png`。
9. 真实窗口验证发现重听按钮中的刷新图标低于文字，判定为 P2；改用显式居中的 `RowLayout`，并加入中心线坐标回归测试。修复证据见 `listening-practice-replay-alignment-final-1536x1024.png`。
10. 首页切换到非四六级场景后仍显示四六级快捷筛选，判定为 P1；删除跨场景重复入口，四六级级别改为只使用选中场景的标准二级分类。修复证据见 `listening-dashboard-scene-visibility-final-1536x1024.png`。
11. 修复后的首页、普通句、长句、音频重点区域和紧凑窗口均未发现剩余 P0、P1 或 P2。

## 剩余 P3

- 原型波形是静态生成图，实现波形来自当前音频 PCM 抽样，因此每道题的峰值位置不会逐像素复刻原型；尺寸、密度、颜色和幅度层级已经对齐，这是有意的数据差异。
- 原型中的少量图标为生成式拟态，实现使用 Material Icons 的可打包真实字形，个别轮廓细节略有不同，但不改变信息层级和交互含义。

## 自动化证据

- `uv run python tools/run_tests.py`：813 个并行测试和 23 个 Qt 串行测试通过，共 836 个。
- `uv run ruff check .`：通过。
- `git diff --check`：通过。
- 截图过程只有无音频后端的离屏 QtMultimedia 环境提示；没有 QML 绑定错误或布局警告。

final result: passed
