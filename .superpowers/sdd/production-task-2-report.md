# Production Task 2 实施报告

## 结论

- 原实现提交 `d6f9784 feat: curate production content quotas` 后，独立审查判定
  **Spec FAIL / Quality FAIL**；当时的 30,000 条 `select` 快照含系统性弱词误分，
  不能作为可发布结果。
- 第二轮独立审查的六项 finding 已全部修复；分类规则升级为 `scene-candidate-v12` 后，
  真实库只读 exact dry-run 可选出 10,989/30,000 条，仍缺 19,011 条。
- `select` 当前明确保持 0 条，没有保留或部分写入旧的 30,000 条快照，不能据此声称
  Production Task 2 完成。
- 当前状态是 **fix checkpoint committed, still awaiting source expansion + independent
  review**。不得开始 Production Task 3 翻译。

## 独立审查失败与修复检查点

独立审查发现三个问题：

1. Critical：`candidate_keyword` 允许单个多义词直接入选；原 selected 中 21,442/30,000
   来自该弱分支，真实误分包括 `show/cold/account/stay/fired/meeting/run/straight`。
2. Important：原无权最大流按来源节点顺序取任意最大流，没有最大化总置信度。
3. Minor：`batch_size or limit or 1000` 会吞掉显式 0，也没有禁止两个批次参数同时出现。

本轮对应修复：

- 删除单词级弱兜底，只允许注册的强领域词、多词短语或同场景双上下文信号；普通多义
  词保留为 `out_of_candidate_pool`。新增真实误分回归，并将分类版本升级为
  `scene-candidate-v11`。
- 选择器改为确定性整数费用的 min-cost max-flow：百万分之一量化置信度严格优先，
  哈希和 ID 只做 tie-break；跨来源反例测试证明高置信候选不再被字典序挤掉。
- `--limit`/`--batch-size` 改为互斥正整数；0、负数和冲突参数均在写库前拒绝。
- 分类修正契约允许 `top_scene/sub_scene` 同时为 `null`，明确把不属于目标场景的审核项
  原子写回候选池外；半空标签仍拒绝，完整 pending 集合契约保持不变。
- 新增单场景及多场景语义召回。多场景只编码一次原型、每个候选 batch 只编码一次，
  统一原子 checkpoint；固定模型 revision 与目录 SHA-256。模型为
  `sentence-transformers/all-MiniLM-L6-v2` revision
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`，目录 SHA-256 为
  `b9a2bf3bf9a916767aa5aa7b5a85a1b0552a42e6a0e57cd31ff72c56383d40ef`。
- `pyproject.toml` 的 content 组显式固定 `sentence-transformers>=5.6,<6` 与
  `huggingface-hub>=0.34,<1`；当前锁定版本为 sentence-transformers 5.6.0、
  huggingface-hub 0.36.2、transformers 4.57.6。模型本体仅保留在 ignored cache。
- 召回读取当前最大可行选择的来源/作者容量，已饱和组合不会挤掉稍低相似但能实际补足
  quota 的候选；容量快照纳入 checkpoint 指纹。lexical-conflict 召回只能使用分类器中
  已注册的强信号，输出触发词、目标分数与竞争场景分数，禁止恢复普通单词兜底。

## 第二轮独立审查六项 finding

1. **C1 分类纯度**：短语改为 token 边界匹配，`recall me` 不再误中 `call me`；每个原始
   token 只产生一个 canonical 形态，`word/words` 不再重复计数。普通单词不能单独入选，
   只有边界短语或至少两个不同 canonical 强概念才能通过；`bill/match/reception/
   prescription/running/law/business` 等真实歧义句均已加入回归。
2. **I1 checkpoint 候选池版本**：语义召回 fingerprint 纳入候选池成员及召回输入内容的
   流式 SHA-256；候选池新增、替换或重分类后，已完成 checkpoint 会失效并从头扫描。
3. **I2 TopK 容量正确性**：semantic 与 lexical 的最终 TopK 使用当前来源/作者已占用量
   做 min-cost 选择。lexical 保留全部匹配；semantic 在固定 reservoir 无法填满可行
   TopK 时自适应扩大并重扫，已覆盖“33 个高分 A、A 只剩 1 槽、低分 B 可用”的反例。
4. **I3 显式拒绝持久化**：LLM 的 `null/null` 结论写为独立方法 `llm_rejected`；初始化
   会迁移历史 `model_version=llm-repair + method=out_of_candidate_pool`，semantic/lexical
   默认查询永不再次召回这些记录。
5. **M1 参数校验**：单场景必须是已注册 `sub_scene`；单场景 CLI、单场景核心 API 和
   多场景配置的 `top_k` 均严格限制为 1..500。
6. **真实库复跑与门禁**：v12 全量重分类、六条指定污染样本、全部 7,420 条 keyword
   证据审计、exact dry-run 和 `select=0` 均已实际验证；没有以测试替代真实数据结论。

## 审核批次与实际增量

所有导入文件均执行精确字段、全量 ID、顺序、合法标签和当前状态复核，再通过完整
pending 集合单事务导入。单批不超过 500 条。

| 批次 | 审核数 | 接受数 | 拒绝数 | 实际可行增量 |
|---|---:|---:|---:|---:|
| 首轮弱候选复核 0001 | 500 | 57 | 443 | 未单独测量 |
| 首轮弱候选复核 0002 | 500 | 135 | 365 | 未单独测量 |
| 语义 top50 门禁（hotel/exams） | 100 | 66 | 34 | 未单独测量 |
| 语义 hotel | 500 | 40 | 460 | 22 |
| 语义 exams | 500 | 96 | 404 | 52 |
| 语义 tourism | 400 | 127 | 273 | 12 |
| 语义 software | 300 | 31 | 269 | 2 |
| 语义 pharmacy | 250 | 71 | 179 | 39 |
| 语义 devices | 200 | 137 | 63 | 79 |
| 语义 meetings | 400 | 30 | 370 | 1 |
| capacity-aware lexical hotel | 100 | 15 | 85 | 15 |

多场景语义文件存在少量 ID 重叠。导入前按当前数据库状态过滤：tourism 排除 4 条已被
hotel 接受的记录；devices 排除 3 条已接受记录，其中 reviewer 拟接受为 devices 的 1 条
已由先前审核归为 software，因此不覆盖既有分类。表中 devices 的 137 是审核接受数，
实际导入当前子集接受 136 条。

审核接受数明显不等于 quota 的实际可行增量：新增记录若来自已经达到 45% 来源上限或
8% 作者上限的组合，只会替换同组合低置信记录，不能补足总量。这个差异驱动了容量感知
召回测试和实现。

## 当前真实库门禁

- 分类版本：`scene-candidate-v12=243,652`；人工结果 `llm-repair=4,002` 保持不变。
- 分类方法：`keyword=7,420`、`context_keywords=5,073`、
  `candidate_source=2,130`、`llm_repair=1,104`、`llm_rejected=2,898`、
  `out_of_candidate_pool=229,029`、`llm_required=0`。
- 六条指定污染记录（611786、247398、638221、595305、616871、631044）均已变为
  `out_of_candidate_pool`；全量 7,420 条 keyword 分类中，单强信号违规为 0。
- 严格只读 dry-run：10,989/30,000，缺口 19,011；protected 300/300 保留。
- 持久化 `select=0`，dry-run 没有写入不完整快照。

当前严格规则证明旧供给远不足以安全填满 30,000 条。下一步应先分析并建立极小、逐词
有真实反例测试的安全单词白名单，只恢复具有唯一场景含义的信号；白名单无法覆盖的缺口
必须通过有明确许可、作者可分散、直接命中短缺场景的新来源补足。完成重新
clean/dedupe/classify、容量感知复核、精确 30,000 选择和独立抽样审查前，Task 2 仍未完成。

## 修复验证

```text
.venv/bin/pytest -q tests/content_pipeline/test_production_classification.py \
  tests/content_pipeline/test_semantic_recall.py \
  tests/content_pipeline/test_lexical_recall.py \
  tests/content_pipeline/test_pipeline_e2e.py
70 passed in 0.50s

.venv/bin/pytest -q -n auto tests/content_pipeline \
  -k 'not test_builder_writes_scene_metadata_stable_ids_and_query_indexes \
      and not test_builder_extends_stable_id_prefix_on_collision'
230 passed in 10.97s

.venv/bin/ruff check tools/content_pipeline tests/content_pipeline
All checks passed!

uv lock --check --offline
Resolved 157 packages in 3ms

git diff --check
（无输出）
```

完整 content suite 另有 2 个 sibling 并行分支引入的 builder provenance fixture 失败：
新校验正确拒绝同场景重复作者，但旧 `build_fixture_database(per_scene=2/3)` 仍复用同一作者。
该范围属于并行 source/release 工作，本检查点未越权修改，也不计为本轮六项 finding 回归。

## TDD 失败证据

首个新增测试运行在 `tools.content_pipeline.classification` 尚不存在时失败：

```text
ModuleNotFoundError: No module named 'tools.content_pipeline.classification'
```

随后测试分别暴露并驱动修正：旧 `--limit` 与新 `--batch-size` 兼容、持久化去重
索引、严格分类导入、500 条批次上限、候选池状态、bounded select、原子失败回滚和
过宽关键词回归。最终新增文件 11 tests 全部通过。

## 实现摘要

1. `clean/dedupe/classify --batch-size` 会循环到无待处理行；旧 `--limit` 仍只处理
   一个批次。
2. 工作库新增事务批次 checkpoint、持久化 SimHash 四分桶及单列索引。去重查询
   使用 4 条独立 indexed SELECT，在 Python 去重候选 ID，再按 500 条批量读取文本，
   不再调用会把几十万行载入内存的 `stage_inputs()`。
3. 分类器增加生产候选池策略、短语信号、可版本化重分类和来源兜底。过宽的
   `way/where/right/left/world/today/yesterday/order/play/lose/work` 等单词已移除；
   对无唯一语义信号的普通记录写入可审计的 `out_of_candidate_pool`。
4. `classify --export-llm` 只导出 `method=llm_required`，每行包含原文、溯源提示和
   32 个合法标签。`import-classifications` 只接受
   `item_id/top_scene/sub_scene/reason`，对额外字段、非法标签、重复/未知/遗漏 ID、
   单文件超过 500 条均在写入前失败；数据库更新为单事务。
5. 300 条 protected 由独立 Codex 子代理逐句按语义分类，生成的 ignored 文件
   `classification-protected.result.jsonl` 为 300 行，SHA-256 为
   `45fd6a46f1f3c589d24ed518921442268d76c7aef5ed95431cff5f5e0d0badea`。
   导入后再次导出待修正队列，因此 `classification-repairs.jsonl` 正确变为 0 字节；
   数据库保留 300 条 `method=llm_repair` 作为审计证据。
6. `select --exact-quotas` 按场景逐个读取固定上限的来源/作者预分层候选，优先高
   置信度，再执行最大流约束选择；32 场景全部成功后才原子替换 select 快照。

## 真实数据运行结果

### 清洗

- 首次：27.66 秒，processed 641,445，accepted 252,199，rejected 389,246。
- 第二次：processed 0。
- 拒绝：too_short 178,329；multiple_sentences 95,958；incomplete 65,961；
  too_long 29,921；sensitive 9,581；unbalanced_quotes 8,980；其余 516。
- protected 在清洗阶段强制保留，最终 300/300 入选。

### 去重

- accepted 247,654；exact_duplicate 2,865；near_duplicate 1,680。
- 第二次：processed 0，且仍报告累计 exact/near 数量。
- 优化后的独立 20,000 条新库基准：1.49 秒，19,943 accepted、57 near，约
  13.4k items/s；索引已增长到 20k 后未退化。

### 分类

- `keyword=14,899`
- `candidate_keyword=78,539`
- `candidate_source=1,447`
- `llm_repair=300`
- `out_of_candidate_pool=152,469`
- `llm_required=0`
- 第二次运行 processed 0，导出的 repair 文件为 0 行。

### 精确选择与抽样审计

下表每场景抽取两个最高置信度句子，并列出最终最大来源/作者占比：

| 场景 | 数量 | 来源 | 作者 | 抽样 1 | 抽样 2 |
|---|---:|---:|---:|---|---|
| culture_books | 700 | 45% | 8% | You have only to read a few pages of this book. | I've read any and every book in this library. |
| culture_movies | 800 | 45% | 8% | That movie theater always shows good movies. | We waited in the movie theater for the film to start. |
| culture_music | 700 | 45% | 8% | He arranged that piano music for the violin. | Violin, piano and harp are musical instruments. |
| culture_sports | 800 | 45% | 8% | Many retired people move to the Sunbelt to enjoy sports such as golf or tennis. | Such sports as tennis and baseball are very popular. |
| daily_food | 1300 | 45% | 8% | Eat not only fish, but also meat. | We eat buttered bread for lunch. |
| daily_home | 1500 | 45% | 8% | She knew what it was like for married women to look after houses, husbands and children. | When we have a family argument, my husband always sides with his mother. |
| daily_shopping | 1400 | 45% | 8% | It cost him five pounds to buy it back. | I paid for the purchase in cash. |
| daily_social | 1800 | 45% | 8% | You need to have friends who can help you out. | Thanks to your help, I could succeed. |
| health_clinic | 800 | 45% | 8% | Communication between doctors and patients is important. | The doctor informed his patient of the name of his disease. |
| health_fitness | 800 | 42% | 8% | Physical exercise and sports can improve fitness. | Dumbbell training became popular during the fitness boom. |
| health_pharmacy | 600 | 44.8% | 8% | The medicine will cure your headache. | This medicine will cure your cold. |
| health_wellbeing | 800 | 45% | 8% | She can express her feelings when she feels happy or sad. | I did not sleep well, though my bed was comfortable enough. |
| news_business | 500 | 45% | 8% | The income tax rate increases in proportion as your salary rises. | The bank rate cut is expected to relieve the financial squeeze. |
| news_current | 600 | 45% | 8% | The group could no longer continue after the new policy. | Peace and development were on the international agenda. |
| news_environment | 500 | 45% | 8% | The sea ice is highly variable during cold weather. | The forest is full of birds and animals of all kinds. |
| news_public | 400 | 45% | 8% | The state government deprived him of his civil rights. | Make equal rights the cornerstone of public policy. |
| study_academic | 1000 | 45% | 8% | The data cited in King's research is taken from a UNESCO paper. | An experiment had to arise from a clear hypothesis. |
| study_campus | 1100 | 45% | 8% | The teacher accused one of his students of being noisy in class. | Some college teachers come to class late. |
| study_exams | 900 | 45% | 8% | We are studying in order to pass the test. | Takeo would pass the exam, but Kunio would fail. |
| study_language | 1000 | 45% | 8% | Look up the words in your dictionary. | I can no more speak French than you can speak English. |
| technology_devices | 800 | 44.4% | 8% | A monitor displays video signals and moving pictures. | The device can pinpoint transmissions. |
| technology_engineering | 700 | 45% | 8% | Early commercial jets sometimes crashed because of technical faults. | Building materials can include tiles and tools. |
| technology_science | 700 | 45% | 8% | Scientific discovery is neither inherently good nor bad. | The gravity of the moon is one-sixth of that of the earth. |
| technology_software | 800 | 45% | 8% | Do you have an account with any social networking sites? | Let a computer program generate your passwords. |
| travel_directions | 900 | 45% | 8% | Turn right at the crossroad. | The restaurant is next door to the theater. |
| travel_hotel | 1100 | 45% | 8% | I'd like to stay for one night. | I'll be staying at the Portside Hotel. |
| travel_tourism | 1300 | 45% | 8% | There are many tourists in the city on holidays. | You need a passport to enter a foreign country. |
| travel_transport | 1200 | 45% | 8% | Passengers shall not converse with the bus driver. | The bus rattled as it drove along the bumpy road. |
| work_contact | 1000 | 45% | 8% | Please send a reply as soon as you receive this mail. | He wrote her a long letter. |
| work_jobs | 1100 | 45% | 8% | White-collar workers may qualify for an exemption. | The applicant was advised to redo her resume. |
| work_meetings | 1100 | 45% | 8% | She attended the meeting at the request of the chairman. | Objections must be referred to the meeting chairman. |
| work_office | 1300 | 45% | 8% | The boss has a good opinion of your work. | Having finished my work, I left the office. |

## 验证命令

```text
.venv/bin/pytest -q tests/content_pipeline -n auto
151 passed in 11.28s

.venv/bin/ruff check tools/content_pipeline tests/content_pipeline
All checks passed!

git diff --check
（无输出）
```

另外执行了真实库二次 clean/dedupe/classify，三阶段均 `processed=0`；再次执行
`select --exact-quotas` 仍产出同一 30,000 条原子快照。

## 剩余风险

- 场景标签是弱监督分类，不等同于逐句人工审核；低置信候选已排除且选择优先高
  置信度，但少量多义句仍可能存在。已通过移除过宽关键词、短语信号和 32 场景抽样
  降低风险。若发布前要求更高场景纯度，建议在 Task 5 再对每场景随机抽样 100 条做
  独立 LLM 审核，不应把候选池外记录自动填入。
- bounded select 的候选上限为单场景 quota 的 16 倍；真实数据已证明全部可行且命令
  可重复。未来来源结构显著变化时，若预分层候选出现假短缺，应扩大固定倍数或增加
  分层轮次，而不是退回全库载入。
