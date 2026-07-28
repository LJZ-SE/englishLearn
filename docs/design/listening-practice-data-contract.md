# 答题页数据契约

## 目的

本契约固定“专注练习台”页面与 Python 业务层之间的数据边界。QML 只负责展示和临时交互状态；题目、作答结果、学习记录、音频缓存和设置均由现有业务层提供并持久化。

## 页面读取模型

| 页面区域 | QML 读取字段 | 类型 | 权威来源 |
| --- | --- | --- | --- |
| 顶栏 | `currentPage` | `string` | `PracticeController` 当前路由 |
| 顶栏 | `difficultyLabel` | `string` | 当前题难度 |
| 顶栏 | `sceneLabel` | `string` | 当前题场景目录 |
| 顶栏 | `progressText` | `string` | 当前题号和本轮题量 |
| 顶栏 | `resourceStatus` | `string` | 离线资源启动校验 |
| 句子 | `sentencePrefix` | `string` | 当前题答案区间之前的原句 |
| 句子 | `sentenceSuffix` | `string` | 当前题答案区间之后的原句 |
| 句子 | `sentenceTranslation` | `string` | 内容库中的完整句子中文翻译 |
| 句子 | `blankCount` | `int` | 当前答案包含的单词数量 |
| 句子 | `currentQuestionId` | `string` | 内容库题目标识 |
| 作答反馈 | `feedbackState` | `string` | `idle/correct/incorrect/revealed/level_up/level_down` |
| 作答反馈 | `feedbackText` | `string` | 反馈文案池的本次随机结果 |
| 作答反馈 | `feedbackAnimation` | `string` | 反馈动画名称 |
| 作答反馈 | `canAdvance` | `bool` | 当前题是否允许进入下一题 |
| 进度 | `progressStates` | `list[string]` | 本轮每题的 `pending/current/correct/wrong` 状态 |
| 进度 | `progressStart` | `int` | 进度编号起点 |
| 进度 | `correctCount` | `int` | 本轮按首次结果统计的正确题数 |
| 进度 | `wrongCount` | `int` | 本轮按首次结果统计的待掌握题数 |
| 音频 | `audioStatus` | `string` | `idle/loading/ready/error` |
| 音频 | `audioSource` | `string` | 当前语速对应的本地缓存文件 URL |
| 音频 | `audioError` | `string` | 离线 TTS 生成错误 |
| 音频 | `audioDurationMs` | `int` | 当前缓存音频时长 |
| 音频 | `waveformLevels` | `list[float]` | 当前音频抽样波形 |
| 音频 | `playbackRate` | `float` | 当前语速 |
| 音频 | `volume` | `float` | 播放音量 |
| 动效 | `animationsEnabled` | `bool` | 本地设置 |
| 词汇本 | `currentVocabularySaved` | `bool` | 当前答案是否已经收录 |
| 离线词典 | `dictionaryRequested(term)` | `signal` | 答案可见后请求查询当前完整答案 |

`stateChanged` 驱动常规字段刷新；`questionChanged` 表示题目上下文已经整体切换；`answerRevealed(values)` 只负责把标准答案逐词回填到现有输入框；`audioRequested(questionId, rate)` 表示当前题当前语速可以开始播放。

## 页面命令

| 用户动作 | 控制器命令 | 业务副作用 |
| --- | --- | --- |
| 检查答案 | `submitAnswers(inputs)` | 校验答案；仅第一次结果写入本轮统计和 `question_progress` |
| 查看答案 | `revealAnswer()` | 回填答案；写入查看答案次数；首次查看按待掌握记录并收录词汇 |
| 下一题 | `nextQuestion()` | 保存当前会话，切换题目并触发自动播放 |
| 播放 | `play()` | 请求当前题音频，不增加重听次数 |
| 重听 | `replay()` | 增加重听次数并请求当前题音频 |
| 调整语速 | `setPlaybackRate(rate)` | 保存设置并切换对应语速缓存 |
| 结束本轮 | `endSession()` | 完成并持久化会话 |
| 返回主页 | `goHome()` | 暂停计时但保留未完成会话 |
| 打开设置 | `openSettings()` | 保存来源页面，设置关闭后返回答题页 |
| 音频重试 | `retryAudio()` | 重新调度当前题 TTS |
| 跳过音频异常题 | `skipAudioQuestion()` | 以同场景、同难度的新题替换当前题 |
| 加入词汇本 | `addCurrentToVocabulary()` | 以 `manual` 原因写入或合并词汇记录 |
| 查看释义 | `requestCurrentDictionary()` | 仅在答案可见后发送查询信号，不修改成绩和学习记录 |
| 选词查询 | `DictionaryViewModel.lookup(term)` | 对当前选中的单词或短语执行只读查询并打开词典抽屉 |

“显示中文/隐藏中文”是纯页面命令，只切换 QML 的 `translationPreviewVisible`，不得调用控制器，不填答案，不修改题目状态，也不写数据库。

## 必须保持的交互不变量

1. `blankCount == answer_word_count`，短语中的每一个单词对应一个输入框。
2. 题目切换时清空全部输入框、关闭中文预览、聚焦第一个输入框，并自动播放一次新题音频。
3. 输入框内按空格只切换到下一个单词输入框；没有输入框焦点时按空格才重听音频。macOS 同时支持 `⌘R`，其他平台支持 `Ctrl+R`。
4. 每次播放或重听之前必须先停止当前 `SoundEffect`，同一题不得叠加播放两个音频。
5. TTS 队列始终按“当前题、后两题”三题窗口预生成并缓存。
6. 第一次答错后再次答对，页面展示正确反馈和欢呼动画，但本题统计仍保持待掌握。
7. 查看答案允许进入下一题，但本题按待掌握记录；它不能转成正确。
8. 正确或查看答案后自动显示完整中文翻译；主动“显示中文”仅预览翻译。
9. 句子过长时按单词和输入框整体换行；波形宽度按句长比例缩短；内容区必须可纵向滚动，核心按钮不能被不可滚动区域遮挡。
10. 无尽模式从简单开始，当前难度连续答对 5 题升级，连续答错 5 题降级，其他情况难度不变；难度边界不越界。
11. 可见英文句子允许鼠标选择单词或短语；仅在存在有效选区时显示“查看释义”右键菜单，查询不得修改答案或题目状态。

## 持久化映射

| 数据 | 数据库表/资源 |
| --- | --- |
| 原句、翻译、答案区间、答案词数、场景、难度 | 内容库 `sentences`、`question_variants`、`scenes`、`aliases` |
| 首次结果、尝试、重听、查看答案、错题复习连续正确次数 | 用户库 `question_progress` |
| 未完成任务、固定题序、当前题、无尽模式难度和连续结果、本轮统计 | 用户库 `sessions.state_json` 及会话索引列 |
| 每日完成题数、正确题数、学习时长 | 用户库 `daily_activity` |
| 单词/短语、来源题目、完整句子、翻译、收录原因 | 用户库 `vocabulary_entries` |
| 音量、语速、动画、每日目标和最近场景选择 | 用户库 `settings` |
| TTS 模型、音频和波形 | 本地离线资源目录及音频缓存目录 |
| 音标、英汉释义、考试标签、词频和词形变化 | 完整 ECDICT `data/ecdict/dictionary.db` |

## 缺口审计结论

方案 1 答题页所需的业务字段、命令和持久化能力均已由现有 `PracticeController`、`PracticeEngine`、`UserRepository`、内容库和 TTS 缓存服务提供。此次页面重构不需要新增后端接口或数据库迁移。

后续只有在原型新增当前契约以外的数据时，才允许先扩展本契约，再修改 Python 业务层和数据库；不得为了页面排版引入重复状态或旁路写入。
