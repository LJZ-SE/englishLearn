# 听写填空学习中心与数据能力设计

日期：2026-07-24
状态：已实现并完成本地回归，待当前版本 Windows 打包验证
视觉基准：[`docs/design/learning-dashboard-prototype.png`](../../design/learning-dashboard-prototype.png)

## 1. 目标

将已经确认的学习中心原型 1:1 落地为 PySide6 + Qt Quick/QML 真实页面，并补齐原型依赖的学习记录、错题本、词汇本、每日目标、长期统计和学习时长能力。

本次开发必须严格遵循以下顺序：

1. 先以视觉基准图实现真实 QML 页面、导航、布局、组件、交互状态和响应式行为。
2. 同时声明页面需要的完整数据契约，页面第一阶段使用确定性的预览数据实现所有状态。
3. 页面通过视觉验收后，再开发用户数据库 v3、查询服务和业务逻辑。
4. 最后用真实数据替换预览数据，完成联调、迁移和全量验证。

不得先按后端现状压缩页面，也不得在后端开发过程中擅自改变已经确认的布局。

## 2. 范围

### 2.1 本次包含

- 固定左侧导航与统一应用框架。
- 首页学习中心。
- 定量练习入口。
- 学习记录页。
- 全局错题本。
- 词汇本。
- 统计分析页。
- 设置页每日目标。
- 答题页手动加入词汇本。
- 答错或查看答案后自动加入词汇本。
- 错题复习连续答对三次掌握。
- 未完成任务详细续练卡片。
- 今日目标、七日趋势、连续学习天数、正确率和学习时长。
- 用户数据库 v1 到 v3 的无损迁移。

### 2.2 本次不包含

- 云同步、多用户账号或联网服务。
- 在线词典、联网翻译或云端发音。
- 社交、排行榜、徽章、会员或支付。
- 修改正式题库内容和 TTS 模型。
- 移动端页面。

## 3. 视觉基准与 1:1 验收

原型图是界面的唯一视觉事实来源。标准验收视口为 1536 × 1024。

### 3.1 固定结构

- 左侧导航栏宽度约 248 px，保持浅蓝底色。
- 主内容区从导航栏右侧开始，使用 24 px 外边距与 16 px 卡片间距。
- 顶部继续练习卡与今日目标卡并排。
- 中部左侧为开始新练习主卡，右侧依次为待掌握和最近练习。
- 底部为七日趋势和五项统计卡。
- 精灵只在左侧导航底部出现一次。
- 右上角保留设置按钮和离线学习状态。
- 页面不出现答题预览、波形、填空句子或屏幕键盘。

### 3.2 视觉规则

- 主色使用 `#1476F2`，正文使用深海军蓝，成功状态使用绿色，错误状态使用暖红色。
- 背景、卡片、边框、圆角、间距、字体层级、图标尺寸和按钮位置均以原型为准。
- QML 组件必须复用统一色板、间距、圆角和字号常量，避免页面间漂移。
- 标准视口下关键元素位置允许不超过 4 px 的几何误差。
- 因 macOS 与 Windows 字体渲染差异产生的字形抗锯齿差异不视为布局偏差，但文字基线和容器尺寸必须一致。
- 960 × 700 到标准视口之间必须可用：侧栏自动收窄为图标模式，主内容允许纵向滚动，不允许按钮被遮挡或页面横向溢出。

### 3.3 视觉验证

- 保存标准视口截图，与基准图逐区域对照。
- 检查侧栏、顶部卡片、中部双栏、底部统计区和所有空状态。
- QML 自动测试验证 objectName、导航、可见性、滚动范围和窄窗口布局。
- 最终在 macOS 真实窗口中验证，在 Windows 打包产物中做一次同尺寸复核。

## 4. 页面设计

### 4.1 应用框架与左侧导航

导航项按原型顺序排列：

1. 首页
2. 定量练习
3. 学习记录
4. 错题本
5. 词汇本
6. 统计分析
7. 设置

当前页使用蓝色高亮。导航底部显示离线资源状态和精灵。点击“定量练习”进入首页并滚动到练习配置卡，不创建重复页面。

### 4.2 首页

首页严格采用原型布局：

- **继续上次练习**：显示场景、子场景、练习模式、已完成数、目标题数和进度条；无未完成任务时显示“开始第一次练习”空状态。
- **今日学习目标**：显示目标题量、已完成、剩余和圆形进度；完成后使用成功状态。
- **开始新练习**：保留现有全部场景、细分场景、CET-4/CET-6、简单/中等/困难、10/20/30 题和无尽模式。
- **待掌握**：显示待掌握总数及三个互斥摘要组。
- **最近练习**：显示最近三轮练习，包含标签、场景、完成进度和相对日期。
- **学习趋势**：显示最近七个本地自然日完成题数。
- **核心统计**：累计完成题次、全局正确率、连续学习天数、总学习时长和待掌握题数。

待掌握摘要分组规则：

1. 多词答案归入“常错短语”。
2. 单词答案中，重复答错或查看过答案的归入“易混表达”。
3. 其余单词答案归入“高频词汇”。

三个分组互斥，数量之和等于待掌握总数。

### 4.3 学习记录

- 默认按最近更新时间倒序。
- 每条记录显示练习类型、场景、难度、完成数/目标题数、正确率、学习时长、日期和完成状态。
- 支持“全部、定量练习、无尽模式、错题复习、词汇复习”筛选。
- 支持继续未完成记录。
- 记录为空时显示明确空状态。

### 4.4 错题本

- 展示首次答错或查看过答案、且尚未掌握的题目。
- 每项显示完整英文句子、中文翻译、规范答案、场景、首次出错时间和复习连对进度。
- 支持场景筛选、关键词搜索、单题移出待掌握和批量开始专项复习。
- 错题复习中连续答对三次后设置掌握时间并移出待掌握。
- 错题复习中任意一次答错会把连对次数重置为零。
- 已掌握记录仍保留在学习历史中。

### 4.5 词汇本

- 答错或查看答案时自动收录当前规范答案。
- 多词答案以完整短语保存，不拆分。
- 答题页提供“加入词汇本/已加入”按钮，手动操作不改变题目成绩。
- 词汇项显示单词或短语、来源句子、句子中文翻译、加入原因、累计遇到次数和最近更新时间。
- 支持搜索、移除和开始词汇专项听写。
- 同一规范化单词或短语只保留一项，多次遇到时更新来源和累计次数。
- 手动移除后，未来再次答错或查看答案可以重新自动收录。

### 4.6 统计分析

- 今日目标与完成比例。
- 最近 7 天和最近 30 天切换趋势。
- 累计完成题次。同一题在不同练习中再次完成会产生新的题次。
- 以每道题第一次结果计算的全局正确率。
- 当前连续学习天数。
- 历史最长连续学习天数。
- 总学习时长。
- 待掌握数量。
- 场景练习分布和难度分布。

连续学习规则：有至少一道完成题目的日期算学习日。当天尚未学习时，当前连续天数允许从昨天向前计算；当天结束仍无学习记录后才中断。

### 4.7 设置

保留现有语速、音量、精灵动画、音频缓存和重置学习记录，并增加每日目标题量：

- 10 题
- 20 题
- 30 题，默认值
- 50 题

修改目标后立即影响首页与统计页，不修改历史数据。

## 5. 页面数据契约

UI 第一阶段只依赖下列只读模型和命令，不直接访问 SQLite。

### 5.1 `NavigationModel`

- `currentPage: str`
- `items: list[{key, label, icon, enabled}]`
- `navigate(pageKey)`
- `openPracticeConfigurator()`

### 5.2 `DashboardModel`

- `resume: {available, sessionId, title, subtitle, completed, target, progress, mode}`
- `dailyGoal: {target, completed, remaining, percent, completedState}`
- `practiceConfig: {sceneCatalog, selectedTopScene, selectedSubScene, difficulty, count}`
- `pending: {total, vocabularyCount, phraseCount, confusingCount}`
- `recentSessions: list[SessionSummary]`
- `trend7Days: list[{date, label, completed}]`
- `summary: {totalCompleted, uniquePracticed, accuracy, currentStreakDays, totalDurationSeconds, pending}`
- `resumeLatest()`
- `startQuantitative(...)`
- `startEndless(...)`

### 5.3 `SessionHistoryModel`

- `filters`
- `selectedFilter`
- `records: list[SessionSummary]`
- `hasMore`
- `setFilter(key)`
- `loadMore()`
- `resume(sessionId)`

`SessionSummary` 包含：

- `sessionId`
- `practiceType`
- `modeLabel`
- `sceneLabel`
- `difficultyLabel`
- `completed`
- `target`
- `accuracy`
- `durationSeconds`
- `completedState`
- `createdAt`
- `updatedAt`

### 5.4 `WrongBookModel`

- `items: list[WrongQuestionItem]`
- `total`
- `sceneFilters`
- `searchText`
- `setSceneFilter(key)`
- `setSearchText(text)`
- `startReview(questionIds)`
- `markMastered(questionId)`

`WrongQuestionItem` 包含：

- `questionId`
- `sentence`
- `translation`
- `answer`
- `sceneLabel`
- `reviewCorrectStreak`
- `requiredReviewStreak`
- `firstWrongAt`
- `updatedAt`

### 5.5 `VocabularyModel`

- `items: list[VocabularyItem]`
- `total`
- `searchText`
- `setSearchText(text)`
- `addCurrentQuestion()`
- `remove(entryId)`
- `startReview(entryIds)`

`VocabularyItem` 包含：

- `entryId`
- `term`
- `sentence`
- `translation`
- `sourceQuestionId`
- `reason`
- `encounterCount`
- `createdAt`
- `updatedAt`

### 5.6 `StatisticsModel`

- `dailyGoal`
- `range: "7d" | "30d"`
- `trend`
- `summary`
- `sceneDistribution`
- `difficultyDistribution`
- `setRange(range)`

### 5.7 `SettingsModel`

- 现有语速、音量、动画和缓存属性。
- `dailyQuestionGoal: 10 | 20 | 30 | 50`
- `setDailyQuestionGoal(value)`

## 6. 用户数据库 v3

升级前使用现有备份机制创建备份，迁移必须在单个事务中完成。
v2 增加学习中心所需字段和表；v3 将旧会话中可确认的完成量、
正确数和时长按日期回填到 `daily_activity`，不对缺失时长做估算。

### 6.1 `question_progress` 扩展

新增：

- `review_correct_streak INTEGER NOT NULL DEFAULT 0`
- `mastered_at TEXT`
- `first_wrong_at TEXT`

保留 `first_correct` 作为全局正确率和第一次结果的事实来源。

### 6.2 `sessions` 扩展

新增：

- `practice_type TEXT`
- `top_scene TEXT`
- `sub_scene TEXT`
- `difficulty TEXT`
- `target_count INTEGER`
- `completed_count INTEGER NOT NULL DEFAULT 0`
- `correct_count INTEGER NOT NULL DEFAULT 0`
- `duration_seconds INTEGER NOT NULL DEFAULT 0`
- `completed_at TEXT`

旧记录从 `state_json` 回填能够确定的场景、进度和累计完成题次。无法确定的历史学习时长写入 0，不生成估算值。

### 6.3 `daily_activity`

- `activity_date TEXT PRIMARY KEY`
- `completed_count INTEGER NOT NULL`
- `correct_count INTEGER NOT NULL`
- `duration_seconds INTEGER NOT NULL`
- `updated_at TEXT NOT NULL`

日期使用设备本地时区的 `YYYY-MM-DD`。

### 6.4 `vocabulary_entries`

- `entry_id TEXT PRIMARY KEY`
- `normalized_term TEXT NOT NULL UNIQUE`
- `term TEXT NOT NULL`
- `source_question_id TEXT NOT NULL`
- `sentence TEXT NOT NULL`
- `translation TEXT NOT NULL`
- `reason TEXT NOT NULL`
- `encounter_count INTEGER NOT NULL DEFAULT 1`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

### 6.5 学习时长

- 进入答题页时开始计时。
- 返回主页、结束本轮、打开设置、进入后台或退出应用时暂停并持久化。
- 回到答题页时继续累计。
- 使用单调时钟计算单次区间，使用墙上时钟归属本地日期。
- 跨午夜区间按日期拆分。
- 同一时间区间只能提交一次，防止重复累计。

## 7. 业务规则

### 7.1 完成题数

- 每道题在一次会话中的首次结果计入完成数。
- 后续重复提交不重复增加。
- 同一道题在另一轮练习中再次出现并完成，会增加累计完成题次，但不会增加去重已练题数。
- 查看答案计完成和待掌握，不计正确。

### 7.2 全局正确率

- 分子：`first_correct = 1` 的题目数。
- 分母：`first_correct IS NOT NULL` 的题目数。
- 第一次答错、之后答对仍保持第一次结果为错误。

### 7.3 错题掌握

- 只有错题专项复习中的首次提交参与掌握连对计算。
- 答对加一，答错归零。
- 达到三次时写入 `mastered_at`。
- 普通练习再次答错会清除 `mastered_at` 并重新进入待掌握。

### 7.4 词汇收录

- 自动收录触发点：当前题首次答错，或首次查看答案。
- 手动收录不改变答题状态、统计或错题状态。
- 使用大小写无关、空白规范化后的答案作为唯一键。

## 8. 实施顺序

### 阶段一：原型页面真实落地

- 建立共享设计令牌和侧栏组件。
- 建立全部新增 QML 页面和导航。
- 使用固定预览模型提供原型中的确定性数据。
- 实现标准视口和窄窗口布局。
- 完成截图对照和 QML 交互测试。
- 本阶段不修改用户数据库，不伪装成真实统计。

### 阶段二：冻结页面数据契约

- 将第 5 节契约落实为 Python Protocol、DTO 和 Qt Property/Slot。
- 为每个页面编写契约测试。
- 预览模型与真实模型必须实现同一契约。

### 阶段三：数据库与领域逻辑

- 数据库 v2 迁移和回滚验证。
- 学习时长记录。
- 每日目标和趋势聚合。
- 会话历史查询。
- 错题三次掌握。
- 词汇自动/手动收录。
- 专项复习会话。

### 阶段四：真实数据联调

- 用真实仓储替换预览模型。
- 删除生产路径中的固定预览数据。
- 验证所有空状态、错误状态和迁移状态。
- 回归现有答题、TTS、续练、设置和打包能力。

## 9. 异常与空状态

- 无未完成任务：继续卡显示首次练习引导。
- 无练习历史：学习记录和最近练习显示空状态。
- 无错题：错题本显示完成状态，不提供无效复习按钮。
- 无词汇：词汇本解释自动与手动收录方式。
- 目标为零不允许写入；设置只接受四个枚举值。
- 数据库迁移失败：保留备份并进入修复页。
- 题库问题：继续使用现有离线资源修复流程。
- 单条历史题目已不在新题库：历史仍展示，专项复习时跳过并提示。

## 10. 测试与完成门禁

### 10.1 页面门禁

- 标准视口与原型逐区域对照，无缺失卡片和导航项。
- 关键几何误差不超过 4 px。
- 960 × 700 下无按钮遮挡、不可达区域或横向溢出。
- 所有页面、筛选、搜索、空状态和弹窗可操作。

### 10.2 数据门禁

- v1 用户库无损升级到 v3，原答题记录和未完成任务可继续。
- 旧数据不生成虚假时长。
- 今日目标、跨日拆分、七日趋势和连续天数边界正确。
- 全局正确率遵循第一次结果。
- 错题复习连续三次掌握和答错清零正确。
- 词汇自动、手动、去重、移除和重新收录正确。
- 会话历史分页、筛选和续练正确。

### 10.3 回归门禁

- 全量 Python 测试通过。
- QML smoke 测试通过。
- macOS 真实窗口视觉与交互验收通过。
- Windows GitHub Actions 打包通过。
- 现有 TTS 自动播放、快捷键、预取缓存、中文翻译、答题判定和设置返回逻辑不得回归。

## 11. 完成定义

只有同时满足以下条件才算完成：

1. 页面在标准视口下与确认原型 1:1。
2. 所有显示数据来自真实本地数据库，不残留预览占位数据。
3. 用户数据库迁移保留原有记录。
4. 新增功能具有完整空状态和错误状态。
5. 全量测试、真实窗口验收和 Windows 打包全部通过。
