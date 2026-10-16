# DESIGN 2026-10-14：Jev 参与经验/方法闭环治理

| 项 | 值 |
|---|---|
| 状态 | draft v0.9.2：P0a/P0b/P1a 已实施；producer 机会分母字段已部署（2026-10-15 13:51 起落地）并经首轮只读审计（附录 v0.9.2，2026-10-16）：窗口 30/30 新 run.end 双键齐备、30/30 可 join、零事件行/配置回退行 0 例；本地 judge 三轮（§11.2–§11.5）主指标 21/37 负向，无资格授予；真 Jev（OpenRouter System One）：R1 6/6 contract_invalid（wire 字段修复，§11.7）→R4 修复轮 6/6 与冻结标签一致；§11.8 v2 扩样 41/43=95.3%（no 召回 13/13、注入 4/4、零高确定错判，牌价≈$0.0001）；合计 47/49 仍 <§9.2 200 条可行性起点，不构成校准资格；尚未获得生产效果资格 |
| 初审/最新复核 | 2026-10-14 / 2026-10-15（Asia/Shanghai） |
| 本轮输入 v0.4 SHA-256 | `47606b0e3f3a6f58ceaa6ff891726a82d57f1a803e2732389e898e77146063bb`；保留其已核方向，仅修订口径 |
| 初次审查基线 | main `5badfc95aadfc286f9c2d8b323cf5932e285c725`；v0.1 当时未跟踪（历史事实） |
| 补充核对基线 | HEAD `2ad0bc06d55aefa3496bdf8c26bad1a4dc2963b2`；初审基线为其祖先 |
| v0.2 入库事实 | `df24e01df5bf3057b9a2586f8e42616f80c0f1f8`（2026-10-14 17:20:40 +0800）；补核前该文件工作树干净 |
| v0.2 SHA-256 | `0443e8540d5337ede81629bfbb33cc7b3cb88b26ce28b6afa1c08bb2314553f5`；v0.3 是本轮文档修订，未在本轮提交 |
| 原稿 SHA-256 | `dcf2200bf8add2b9640390a58b80f1885eba72c13665b9f191b47eb3185a2df0` |
| 定位 | 先补知识消费的证据与对账，再验证可选外部判断能力；模型保留语义终裁 |
| 关联 | `METHOD_LEARNING_V1.md`、`CHANGES-20261007-method-consumption-closed-loop.md`、`PLAN-20260926-learning-method-semantic-integration.md`、`ai_rules.md` Rule 18/22/29/31、`DEVELOPMENT_REPAIR_SAFETY.md` |
| 本次变更范围 | 修订本设计（§11.7 R4 修复轮预注册冻结 + 状态/表格同步）；实施契约符合性修复：`src/llm_loop/knowledge/jev/{wire,shadow}.py`、jev 定向测试三件、`tests/fixtures/jev/blind_eval_v1/`（wire 样本官方字段名 + manifest 重冻，cases/labels 字节不变）、包外 runner/local transport（R4 口径）；R4 真实外发仅限 §11.7 预注册并经用户 12:29 "修" 授权的同任务集 2 请求/6 题；未改 Rules、配置、资产生命周期；未部署、未重启任何服务 |

> 本文区分【已核事实】【分析】【拟实施要求】【待实测】。读取源码证明的是该基线的实现，不证明 live 已加载或效果已经成立。文中已存在的事件/模块见 §1.3；增量字段、判断/贡献事件名、schema、策略档与阶段闸均是提案，不是现有 API。

## 0. 审查结论与优先级

**建议有条件采纳“结算先行、原子问题、独立校准”；暂缓把 Jev 接进默认检索顺序。** 闭环的目的应是减少错误与返工、帮助模型看到事实并自主取舍，而不是增加知识调用、采用声明或控制器数量。

| 优先级 | 修订方向 | 为什么先做 | 验收边界 |
|---|---|---|---|
| P0 | 复用已存在的观测/传输/终局链，补字段与可靠性缺口 | 净分、账本、10种知识事件、EventStore、SessionDigest 已有；不另造相同 producer/journal | §1.3–1.4 已完成静态盘点，P0a 只审计范围内真实样本与剩余缺口 |
| P0 | 曝光、使用声明、事实标签、收益归因四者分开 | 没读到不等于拒绝；成功不等于条目有效；采纳不等于前提为真 | unknown 保留，事实与声明分栏，不能自动相互推导 |
| P0 | 保存/任务交付不依赖 Jev 与异步结算成功 | 新组件不可成为“存不下教训/任务卡住”的依赖 | 故障可降级、结算可恢复、正文交付不等待外部判断 |
| P0 | 可见性与模型否决出口写入契约 | 只排序仍能通过 top-k/字符预算隐藏候选 | 原检索可用、exact ref 可读、裁剪可发现、模型可绕过建议 |
| P1 | 对账与盲评先于排序试验，校准与收益分别验收 | “Phase 1 不对账、却用命中率切换”不可执行 | shadow 同时产出独立事实标签；未达标继续 HOLD |
| P1 | 采用官方多问题 API，控制总调用/Token/延迟/队列 | 原稿的单问单发和 k×p 并发会重复上下文、放大成本 | 一次 HTTP 可含多道独立题；依赖题分阶段；SDK 隐式重试关闭 |
| P2 | 去重、分类、helped_hint、权重建议逐项验证 | 一次引入全部能力会失去归因 | 每种用途独立结果、独立开关/策略版本和回滚；helped_hint 首轮不做 |

**当前推荐下一项**：从现有完整 EventStore（包括滚动分段）、两侧 usage ledger 和 SessionDigest 做 Provider-free 的覆盖审计与只读投影；用 `run.end` 作更广的“已记录结束事件”索引，`knowledge.*` 作可选增强。已有历史及近期知识事件，不需要为了这一步先开 shadow 造样本。运行样本数量、来源配置、进程实际 mode、语义收益分别核验，不能相互代替；缺少明确 run/task 身份时只产 unknown/关联候选，不能按同一 session 强行归因。P0a 本轮已完成分段计数和重复身份初核，下一项只核剩余关联/业务标签缺口。本设计不授权任何外部调用或上线。

## 1. 当前事实：已有能力与实际缺口

### 1.1 源码和历史文档核对

| 已核事实 | 权威入口 | 对本设计的约束 |
|---|---|---|
| Method discovery 支持词法与可选语义 RRF；exact `method:<id>` 不走语义 fallback，适用性仍未评估 | `src/llm_loop/introspection/search.py::_search_method`；`METHOD_LEARNING_V1.md` | 基线称“当前已解析的词法/语义检索”，不能泛称“纯嵌入” |
| Method 与 Experience 都有四态使用声明账本，声明不等于收益；记录版本/投影 hash 与运行身份 | `methods/store.py::record_use`；`experiences/store.py::record_use` | 复用原账本，不能在 settlements 再建立第二份 use 真相源 |
| 使用净分和阈值提示已存在；分开显示 applied、not_applicable、rejected；只提醒不执行处置 | `src/llm_loop/usage_net.py`；两侧 `usage_net`；`search.py::_annotate_usage` | 缺口是曝光分母、独立事实标签、收益归因和可恢复对账，不是“没有任何调优管道” |
| 计分实现把未验证 applied/adapted 也计 +1；Rule 31 正文要求结果验证有效 | `usage_net.py` 模块契约与 `docs/ai_rules.md` Rule 31 | 分别标注“声明净分”和“验证收益”；本设计不静默改 Rules 或既有算法 |
| 当前重锚以账本 status 尾段估计最近 transition；status 往返不可辨；非状态修改不自动重锚 | `usage_net.py` D3；Rule 31 程序角色说明 | 新评估必须绑定 content hash/revision；净分不是精确内容版本质量 |
| 新正向 experience 要求 verified+evidence；未验证/证伪内容应走 lesson；legacy 不自动升格 | `introspection/tools_experience.py::run_save_experience`；`experiences/document.py` | 删除“所有新经验恒为 unverified”的原稿模板，沿用现有学习记录契约 |
| Experience `scenario` 是字符串，解析器只支持极简 YAML 子集 | `experiences/document.py` | 嵌套 preconditions 不直接塞回原主文件；先用带版本的派生 sidecar |
| Method 已有 freshness_refs 与 freshness 展示，经验保存有当前性验证动作校验 | `search.py::_search_method`；`tools_experience.py` | 不另造第二套相互冲突的新鲜度来源；先映射现有字段 |
| 10-07 文档记录 B 面“记忆检索工具回执附 Method 尾注”；当前 `src/` 与 `tests/` 未找到该前台 search 分支或 `test_method_related_hint.py` | `CHANGES-20261007-method-consumption-closed-loop.md`；`introspection/search.py` | 只收窄到该 B 面工具回执路径；不推断全仓没有前台候选能力，见 §1.3 KnowledgeAdvisor |
| Learning Reflection 的 `_discover_related_methods` 确实存在，调用/装配于 493/508，536 声明候选适用性未评估 | `src/llm_loop/methods/reflection.py:417`；历史集成计划 | 这是 Reflection 候选发现，不是 B 面 search 回执尾注，也不是下述 KnowledgeAdvisor 前台尾注；三条路径分别核验 |
| 当前 `src/` 与 `tests/` 未发现 Jev/TypeSafe client；已有知识观测与摘要载体，但尚无本设计的独立判断标签/贡献评估实体 | `knowledge_runtime.py`、`knowledge/` 子包详见 §1.3；源码检索 | 把“已有观测链”与“尚缺贡献/标签”分开；provider settlement 与 fleet settlements 是另外两个领域 |

这些事实不证明当前 Rule 31 净分存在运行故障，也不证明 B 面曾经无效；只是防止设计以历史描述代替当前基线。

### 1.2 缺口应如何表述

【分析】需要回答的具体问题是：
1. 候选是否实际进入模型收到的请求，而不只是被搜索器召回？
2. 模型在什么任务、什么版本上声明应用/拒绝？未声明的原因是未知还是未呈现？
3. 哪项前提有当时证据？前提真假与最终任务结果能否分别核验？
4. 收益是主模型自报、有机制证据支持，还是独立对照证明？
5. 版本修改、终局重放、中断恢复时，账本与结算是否保持一致？

Jev 只可能补充第 3 项的有界建议以及部分重复识别辅助。第 1、2、5 项已有观测和恢复基础，接下来核覆盖与缺失字段；第 4 项主要缺独立收益证据。不能用外部模型替代这些工作。

### 1.3 已有知识观测链：10种事件生产点与3个模块

【已核源码，不是 live 运行证明】下表事件由 `src/llm_loop/core/loop/engine_services/knowledge_runtime.py` 的 `KnowledgeRun._emit` 生产，行号对应补充核对 HEAD。与初审 `5badfc95` 比较，该 runtime、`knowledge/` 子包、advisor 和 provider_settlement 相关源码无差异：这是初审时已经存在、但 v0.2 漏盘的基础，不是后续才新增。

| 已有事件 | 生产点（knowledge_runtime.py） | 已记录事实与限制 |
|---|---|---|
| `knowledge.discovery` | before_provider:244 | frontier、trigger、筛选后的 hints、投影指纹/诊断；applicability=not_evaluated；不是原始召回池全集 |
| `knowledge.reference_prepared` | before_provider:254 | refs、reference_chars；provider_delivery=not_confirmed，准备不等于送达 |
| `knowledge.hydration_observed` | observe_receipts:130 | 配对成功工具回执中的 exact 水合；adoption=not_evaluated |
| `knowledge.method_declaration` | observe_receipts:135 | call/ref/decision、hydration_observed；task_benefit=not_evaluated；原 usage ledger 仍是声明真相源 |
| `knowledge.experience_declaration` | observe_receipts:161 | 校验声明回执并记录验证态/投影 hash；明确只作审计对照，不替代经验 usage 账本 |
| `knowledge.run_outcome` | finish:294 | reason、轮数/Token/耗时、模型、run_incomplete、hydrated_refs；不判任务成功/知识收益 |
| `knowledge.failure_observed` | observe_receipts:100 | 首个真实配对工具失败；root_cause=not_evaluated |
| `knowledge.followup_tool_observed` | observe_receipts:203 | 失败后工具事实；recovery_proven=false，不把后续成功当根因修复 |
| `knowledge.learning_saved` | observe_receipts:194 | 已确认 stable save ref 与首失败关联；independently_validated=false |
| `knowledge.learning_unconfirmed` | observe_receipts:187 | 没有 exact confirmed save ref；不冒充成功落库 |

LFL反馈所列另外三项是已存在的 Python 模块/载体，**不是本轮发现的同名 EventStore 事件生产点**：

| 模块 | 实际能力 | 复用与证据上限 |
|---|---|---|
| `knowledge/injection_ledger.py::append_row` | 工具回执提示/水合的独立 JSONL 观察账本，factory/registry 接线，fail-open | 可作曝光审计线索；不是 usage 真相源；该路径无 fsync/跨进程去重承诺 |
| `knowledge/digest_receipts.py::transport_pairs/_pair` | 将 prepared 与 provider.transport.opened/settled 按身份、顺序、refs、字符数和SHA结构关联 | 保留 http_success_observed / http_error_observed / unknown；model_attention 永远 unknown |
| `knowledge/session_digest.py::SessionDigestReader` 与 CLI | 从 canonical EventStore 建只读投影，event ref/hash、coverage、分页、currentness与exact事件恢复 | 现成复用；task_success/task_benefit=not_evaluated；CLI/reader存在不证明所有模型工具面已暴露 |

完整接线还包括：

- `introspection/knowledge_advisor.py:111/131`：off/shadow/canary，任务 frontier 的有界 Method/Experience/Lesson 发现；`core/loop/build.py:649–657` 在 mode off 时不执行该路径。
- `knowledge_runtime.py::project_execution_knowledge`：canary 引用尾注需当前签名 Web ingress、session allowlist、low-risk 与字符余量；shadow 不改 wire。这是前台能力，但**不是 B 面的记忆检索回执尾注**。源码默认、当前非密来源赋值与事件样本分开核对，见 §1.3.1；未核所有 live 进程的 resolved mode。
- `runtime/resolver.py:447–454`：拒绝全局 knowledge_advisor 配置，只支持服务级 Web 配置；不能静默扩到 Feishu/Learning。
- `KnowledgeRun.provider_reference_facts:262`：在已准备引用与最终 OpenAI 形态 payload 的 user 字符串后缀之间匹配 exact bytes，生成 reference_sha256；其它 wire 形态保持未观测。
- `llm/client.py:1369–1378` 调用 knowledge probe，将其写入 prepared；`resources/provider_settlement.py:442–460` 持久化前作有界字段类型/长度筛选。此处不是独立重算源 hash，也不是远端“已阅读”证明。
- `run_finalizer.py:460–474`：存在 tracker 时调用 finish；随后 :476 起追加通用 `run.end`（独立 try，不依赖 tracker）。故现有终局出口应优先复用，不另找一个无关联的 producer。

#### 1.3.1 来源配置、已有样本与完整扫描（v0.5复核）

【已核】代码默认off；当前根 `.env:266` 的非密赋值是 `LFL_KNOWLEDGE_ADVISOR=shadow`；EventStore中已有历史及近期知识观测事件。因此“整条链关闭/没有样本”的推论不成立，P0a不需要先开启新的采样。

**证据上限也必须区分**：
- `.env` 是来源配置，不等于所有已启动进程的实际值。`runtime/resolver.py:604–646` 还处理服务边界、CLI、允许的shell override、服务级TOML与dotenv优先级；本轮未核所有live PID/manifest的resolved mode。
- `git check-ignore .env` 确认该文件被忽略；`git grep` 不能从忽略文件读取这条赋值。搜索零命中不是“未启用”的证据，但不能因此反过来把Git一概排除于源码/配置来源核对。
- 既有 `knowledge.*` 的payload未统一记录mode与部署generation；事件证明观察事实曾被记录，不单凭事件总数证明每天、每服务、每实例均运行shadow。历史 `reference_prepared` 的canary路径也不能混称shadow。
- “样本已存在”足以撤销开采样这一步；“足以进行收益/校准评估”需要真实曝光、应用、独立标签与对照，不由总数决定。

**扫描范围纠正**：v0.4使用 `data/event_logs/*.jsonl`，只覆盖顶层单文件会话。现有EventStore还支持 `data/event_logs/<session_id>/<segment_seq>.jsonl`；`read/read_source_files` 会读取多段。正式审计优先走这两个接口，不以顶层glob冒充完整来源。

本轮只读流式扫描冻结每个文件的初始长度，解析事件顶层type/ts/session_id及payload；只输出聚合计数，不导出消息/工具正文。固定上界为 **2026-10-15T00:08:59.999999+08:00**，没有给run.end另加起始日期。该边界比v0.4“00:08”更明确，不声称精确复现其秒级结束时刻。

| 口径 | 顶层单文件 | 滚动分段 | 完整范围 |
|---|---:|---:|---:|
| JSONL文件数（本轮捕获） | 830 | 337 | 1167 |
| `knowledge.*`事件 | 3374 | 11350 | 14724 |
| knowledge session | 92 | 26 | 118 |
| `knowledge.run_outcome` | 191 | 299 | 490 |
| `run.end`事件 | 2192 | 2326 | 4518 |

完整范围的knowledge共有568个不同run_ref；run.end分布于667个session。knowledge最早为2026-10-09 05:34:47，固定上界内最后为2026-10-15 00:08:58。逐日计数为1436/2966/1352/1105/4530/3249/86，合计14724。

| knowledge类型（固定上界完整范围） | 数量 |
|---|---:|
| followup_tool_observed | 13094 |
| discovery | 678 |
| run_outcome | 490 |
| failure_observed | 294 |
| learning_unconfirmed | 87 |
| learning_saved | 30 |
| experience_declaration | 25 |
| method_declaration | 15 |
| hydration_observed | 9 |
| reference_prepared | 2 |
| 合计 | 14724 |

**v0.4计数不能作为全量口径继续引用**：其run.end=2192与本轮顶层口径一致；遗漏分段是主要差异，不是几分钟的新事件能解释。原报告“1904个会话文件”也没有区分JSONL、锁文件和目录。本轮目录项含830个顶层JSONL、977个lock、100个分段目录及1个其它项；它们不是1908个会话文件。顶层与分段无同名会话重叠，337个段名均为数值。

v0.4还存在内部加总不一致：总数3368、逐日和3370、类型和3363、distinct2989+重复381=3370。可能涉及采集时点/口径混用，但本轮未取得其原脚本/完整回执，不能指定根因。本轮使用同一过滤范围重新计数，不猜改原分项以凑总数。

**重复判据纠正**（全部字段在payload；schema中不存在对应data层）：
- 裸key：14724行、14044个非空不同key、重复超额680（Σ每key的count−1）。
- 业务身份初核：`(session_id, run_ref, event_type, knowledge_event_key)` 的重复超额为 **0**；同身份冲突payload组为0。
- `KnowledgeRun.finish` 固定使用key=`terminal`，不同run合法复用；其它事件也可能在不同类型/作用域共享key。裸key重复不能证明重复写入、二次评分或去重缺陷。
- “本窗口未观察到同身份重复”不等于协议已具备跨重启exactly-once，也不证明use账本在线幂等；§1.4的源码边界保留。不能据裸key计数去删事件或补去重器。

**run.end更广，但不是完整运行全集或可直接join的主键**：它不依赖knowledge tracker，但普通append仍fail-open，进程被杀/没走finalizer可能没有它。在本轮4518条run.end的payload中，run_ref/run_id/generation/episode_ref/task_id的非空计数均为0，源码finalizer与KPI也没有添加这些字段。只读投影可用 `(session_id,event_id,seq)` 标识结束事件；关联knowledge/use时须有额外明确身份/时序证据，多run共用session或重入时必须保留ambiguity，不允许“取最近一条”当同run证明。

审计分母必须是同服务、同时间窗、同启用/任务机会范围；本表run.end上界前的历史范围比knowledge首次出现更宽。不能用490/4518直接称“知识终局覆盖率”，更不能用completed当任务验证成功。无结束事件的open/interruption需依既有request.meta、execution/checkpoint与恢复事实单列，不能自动补造run.end。

**捕获完整性说明**：初始JSONL字节合计3755925438；文件元数据清单SHA-256为 `3d5f8ae9356e8cc6cdf638d09f68a6b82b9df4ebb03a0f14d1526c55708c3fa6`，它是文件名/长度/mtime清单指纹，不是事件原文字节hash。本次相关行解析失败、读取错误、未完成尾行、扫描中发生变化的文件均为0；未据此宣称所有非相关事件均通过canonical完整性校验。正式case证据继续使用EventStore/SessionDigest exact event refs与hash。

以上都是该工作区、该过滤范围的本机读数，不等于其它部署/release，也不证明Jev效果、经验收益或主模型attention。2条prepared、9条hydration与40条使用声明说明关键链路仍稀薄；其原因待核（实际机会/模式/工具可见性/版本/回记），不能预先判成bug或无效。

### 1.4 复用优先，但不能越过已核能力边界

| 核对项 | 已能关闭的部分 | 仍须核对/不成立的推论 |
|---|---|---|
| Q1：事件与恢复载体 | EventStore及SessionDigest已存在；事件具备 session/seq/event_ref/source hash 与分页 | 普通 append 为flush、fail-open，不是强 fsync/事务成功；KnowledgeRun._emit 不核写入返回，不能直接充任必达结算 intent |
| Q1：幂等 | KnowledgeRun 的 keys/call_ids/finished 做 run 内内存去重；经验迁移 `record_migrated_entry:892–911` 按 knowledge_event_key 跨进程锁内去重 | 普通 `record_use` 不传 dedupe_key；EventStore.append 生成新event_id，不按业务 key 去重；不能推论在线 use/跨重启贡献投影已幂等 |
| Q2：terminal producer | run.end在tracker块外追加，已记录结束事件更广；knowledge.run_outcome作增强 | run.end fail-open且缺明确run/task identity；退出遗漏、服务/时间窗/机会分母与关联歧义见§1.3.1，不能强join或称完整全集 |
| Q3：使用/版本/传输关联 | Method usage有method_content_hash；Experience有document_projection_sha256；run_ref与knowledge_event_key可连接传输 | 观察事件可能缺失；discovery的projection:指纹不是全文hash；旧声明未必有task identity；不能猜补或当同一事务 |
| 名称边界 | 10种knowledge事件、3个knowledge模块、provider传输结算、fleet workspace结算已区分 | grep模块路径不能计作事件；reference材料不能计作独立参考标签；跨域“settlement”不能混算 |

**持久性具体边界**：`event_log/store.py::append:325` 经会话锁写入；`_append_locked:583–611` 是write+flush，普通append没有上述业务去重或fsync确认。专用 `append_durable_human_message:368` 的更强语义不能自动借给知识事件。这里记录的是现有设计取舍，不在本轮改程序或扩建通用预算/存储架构。

v0.2 的 `src/tests` 写法确实不准确，v0.3 全部改成两个根 `src/` 与 `tests/`。初审实际工具使用的是这两个独立根，并非检索不存在的目录；错误在报告表述。对“13种事件”也用生产点而非路径计数修正，避免以新误述替换旧误述。

**v0.6 P0a 审计结果交叉引用**：上表的数量/窗口/类型分布已独立复算并逐项对齐（脚本 `outputs/jev-p0a-20261015/recount.py`）；退出遗漏、同范围分母与关键稀薄链路的审计结论见文首「v0.5→v0.6 P0a 关联与覆盖审计」一节与 §13 待关闭项 1/2/3 的更新。事件字段名是 `type`，不是 `event_type`。



## 2. 反例拷问：原稿哪些假设站不住

| # | 拷问 | 分析结论与修订 | 可证伪条件/验证 |
|---|---|---|---|
| Q01 | 主模型已有理解能力，为何还要一个判断层？ | 仅在可重复原子任务上可能节省成本/提升一致性；不是修复“主模型智力不足” | 与无 Jev、主模型自行判断分别比较；无收益则保留能力 OFF |
| Q02 | “只排序不删除”真的不减能力？ | top-k 和字符预算使排序影响曝光；原稿“完整可见”无证明 | 最后呈现 manifest、provider-visible 回执、分页/exact 恢复；候选被裁后无入口即失败 |
| Q03 | 一道关键前提为 no，四道无关前提为 yes，会否得到高分？ | 满足率会稀释必要条件；不采用简单乘积或平均 | required/all、any-group、optional、counterexample 分开；模型处理矛盾 |
| Q04 | unknown=0.5 为什么是“中性”？ | 乘积会惩罚字段缺失和前提多的卡；未知没有数值真相 | unknown/invalid 不改基线排名，不标“不适用”，缺失事实可按需核验 |
| Q05 | 任务成功能否反证前提成立、证明 helped？ | 不能；主模型可能绕开错误方法才成功 | premise actual、task outcome、contribution 三个标签独立 |
| Q06 | 一条经验被 not_applicable 两次是否应该淘汰？ | 是场景不匹配信号，不能推成内容错误 | 净分提醒沿用；处置需独立反证/修正理由，不能自动 invalidate |
| Q07 | Jev 高置信冲突能否让保存挂起并强制人审？ | 不能；这会把建议偷偷升为否决权 | 保留原保存路径；Jev 提示可被模型拒绝；只有既有真实权限边界可拒绝写入 |
| Q08 | Rules “零参与”又送去做冲突检查是否一致？ | 原稿自相矛盾；v0.2 明确 Rules 不外发、不排序、不参与校准/调权 | 任意 rule 请求不得进入 Jev 调度/批次/投影；相关性由主模型读权威规则判断 |
| Q09 | 同根因是否等于重复、可以合并删除？ | 不等于；环境/版本/动作不同可能是有价值反例 | 只建议 same-root/distinct-case；合并由模型决定，保留原文与 refs |
| Q10 | 要求每条教训先抽结构化前提，会否漏存最关键发现？ | 会；抽取不应成为新保存门槛 | 保留原 scenario/全文；抽取失败或无前提均允许保存，标 extraction_state |
| Q11 | 从短摘要能否判断完整任务适用性？ | 只能判断所给快照；摘要未知不能作否定证据 | context source/coverage/hash 显示；缺字段返回 unknown，不主动遍历全文 |
| Q12 | Jev 预判与采用决定一致，是否就叫校准准确？ | 不是；看过预判的主模型易产生共同偏差 | 首批参考标签对 Jev 输出盲化；争议记 disputed/unknown，不强行回填 |
| Q13 | Phase 1 不对账，如何一周后按命中率切换？ | 无法；时间不是资格 | Phase 1a 就建独立对账；按样本与区间切换，旧版不可调用时与固定基线比较 |
| Q14 | 全 top-k 已可见，为何还要把低分候选再注入尾部？ | 会重复而未增加覆盖；尾部也可能被裁 | 仅有限曝光时探索；不复制已呈现项；保留基线曝光对照 |
| Q15 | 一请求一题是否是 Jev 的硬限制？ | 不是；官方支持共享 state 的命名 questions | 逻辑原子不等于物理单发；小批量打包独立题并检查逐题响应 |
| Q16 | 无 confidence 填 0.5 是否诚实？ | 不是；缺失不是估计值，confidence 也不是命中概率 | schema-invalid→不参与排序；原值保留 null；校准预测概率和经验准确率分开 |
| Q17 | 结算钩子失败可否让 completed 任务继续等？ | 新结算不可阻塞任务；也不可假称落盘 | durable intent、幂等重放、有限重试与状态告警；已有交付闸不在本设计中改动 |
| Q18 | helped_hint 由同一判断器给标签，是否形成闭环？ | 是自证循环风险；首轮不接入 | 辅助建议永远不能成为其自身校准真值；人/独立盲评与执行证据分别记录 |
| Q19 | v1.13、94.7%、月更、P95<2s 能否直接写验收？ | 版本可按官方页核对；准确率/更新周期/本机延迟不能借用 | 钉住响应 resolved model；中文/长上下文/冲突场景独立测量 |
| Q20 | 回滚=关开关是否“零风险”？ | 已外发数据、已改资产、已产派生污染不会自动撤回 | 停调度、隔离投影、保留账本、取消队列、核 in-flight；删除/修复按独立流程 |

## 3. 目标、非目标与模型能力底线

### 3.1 目标

- G1：沿用原知识工具，让模型更容易发现、精确回读、比较和拒绝建议。
- G2：建立曝光→声明→贡献归因→独立标签的可审计链；每层可标 unknown。
- G3：Jev 作为可选判断能力，首先 shadow；每种题型独立证明质量、成本和延迟。
- G4：在成功率不退化的前提下，优先减少返工、错误重试与全任务 wire 成本。
- G5：检索、保存和主任务在 Jev/投影失败时仍按现有契约完成。

### 3.2 非目标

- 不新增 universal prompt、不注入全库 Method、不强迫简单问答跑治理流程。
- 不使用 Jev 决定 Rules、资产状态、任务终局、Provider 路由或工具权限。
- 不把经验冷热度、年龄、unknown、采用率或净分变成自动删除/失效依据。
- 不重写现有 record_use、qualification、Learning 或 Rule 31。
- 不保存、重构或外发隐藏 reasoning_content/思维链。
- 首轮不做 helped_hint，不承诺“接入外部模型就提升智力”。

### 3.3 模型的否决与恢复出口

模型可继续使用既有 `search_records`，精确水合 `method:<id>` / `experience:<id>`，查看原始证据并拒绝 Jev 建议。拟引入排序时，应在同一检索入口提供显式“原基线顺序”能力；字段名待工具契约审核，不先造平行搜索工具。

此出口不需要对语义分歧进行人工审批，也不得要求模型证明 Jev 错了才能绕过。授权、隐私和物理资源边界仍按既有契约执行。保存/检索本来可做的事情不得因 Jev 的建议变得不可做。

## 4. 职责与权威：事实由程序保真，语义由模型判断

| 对象/动作 | Jev | 主模型 | 程序 | 用户/既有治理 |
|---|---|---|---|---|
| 原子前提/重复/分类 | 输出非权威建议 | 选择是否参考、核证、拒绝 | 校验结构、身份、预算，记录原值 | 按需复核 |
| Rules | 不读取、不接收、不评估 | 按现有规则读取并执行 | 现有索引/权限；与新统计结构性隔离 | 修改沿用既有审批 |
| 检索呈现 | shadow 无影响；排序试验才可用 | 可恢复基线/读全文 | 显式批准策略的机械实现，不推断任务重要性 | 确认排序试验范围 |
| 保存与使用 | 不阻塞、不合并、不改原卡 | 原保存契约、四态声明 | 保真保存、原账本审计 | 既有维护权限 |
| premise 真值与 helped | 无资格作为自身真值源 | 带可见证据的初判 | 引用/版本/覆盖核验，不能证明语义真伪 | 独立盲评处理争议 |
| verified/disproven 与 Method 晋级 | 无权 | 提议/现有合法动作 | 既有机械证据/身份闸 | 既有生命周期契约 |
| 调优与处置 | 无执行权 | 评估建议、可否决 | 只产投影/建议 | 已有授权范围内确认，越界才另行审批 |

“用户唯一能改 Rules”不能被误写成“模型连获批的规则维护也禁止”。本文对新判断器实行零 Rule 参与；现有 owner 授权的规则维护流程保持原契约。

## 5. 数据契约：单一真相源、版本绑定、声明不冒充效果

### 5.1 在既有观测/恢复载体上补增量，不先建新journal

【已核事实】原 Method/Experience 文件、usage.jsonl、qualification/transition receipts 保持各自真相源。KnowledgeRun→EventStore→SessionDigest 已提供运行观测/只读恢复；injection ledger 另作提示观察。先审这些载体对新要求的覆盖，不再提出“先确认有没有事件源”。

【拟实施】默认复用 EventStore、SessionDigest与原usage，Web/Feishu/Learning只作adapter。投影可重建，不能覆写原审计。只在样本或故障证明现有契约不足时，提出具体增量字段、贡献revision或局部持久intent；不先添第二份use账本、通用终局producer或新后台worker。

v0.2四个拟新增事件族经名称/语义撞车审查后调整如下；新名在补核 `src/` 范围内未发现生产点，注册/落代码前仍要再核：

| v0.2提案名 | v0.3处理/提案名 | 需要的增量与禁止推断 |
|---|---|---|
| `knowledge.retrieval_snapshot` | 优先增补已有 `knowledge.discovery` 字段与projection；不默认新增事件 | 现有hints不是全集；需raw/kept/pruned、基线顺序、版本/覆盖及实际呈现关联；召回≠阅读 |
| `knowledge.judgment_attempt` | `knowledge.judgment.attempt`（拟新增） | 外部结构化题的逻辑/物理身份、模板/上下文、原值与逐题状态；成本仍关联既有provider尝试，不能双记 |
| `knowledge.settlement_revision` | `knowledge.contribution.revision`（拟新增） | 引用已有run/terminal、use账本与证据，新增贡献评估revision；不是provider计费结算或fleet workspace结算 |
| `knowledge.judgment_reference` | `knowledge.judgment.label`（拟新增） | 独立actual标签、来源、证据、争议/版本；不与reference_prepared/knowledge_references引用材料混用 |

名称既要区分domain，也要记录 `schema/domain` 和来源身份。标签字段改 `label_state/label_revision`；既有 `reference_*` 字段保持原语义，不做破坏性重命名。

新增事件只记录已观察事实或显式语义声明；不能为凑四态补写record_use。SessionDigest可连接原事件/声明/HTTP事实，但不能自动评估helped或真实任务成功；新贡献与标签才是独立评估缺口。

### 5.2 统一身份与时间

每条事件绑定 `workspace_scope/session_id/run_id/episode_ref/task_id` 中真实可得的身份。goal_id 可空：一个 Goal 可跨多个 task/episode，不能以“当前 Goal”替代原发生身份。字段缺失保留 unknown，不猜。

- subject：`asset_layer=method|learning_record`；learning_record 另保留 `record_kind=experience|lesson`，避免遗漏失败教训。
- 版本：Method content hash；Experience 既有 `document_projection_sha256`，注明它是重序列化投影 hash，不能冒充磁盘 exact bytes hash。新增 exact source hash 时单独命名。
- 排序/抽取/标签均绑定 subject revision/hash、context snapshot/hash；修改后的卡不继承旧版效果资格。
- 结算幂等键：真实 task/run terminal-event identity + schema version；更正采用追加 revision + supersedes，不覆写历史。
- 同 status 往返不能识别为“没修改”；内容版本与 lifecycle transition 分开绑定。
- 只保存有限规模、与问题有关的上下文；本地受控快照与脱敏外发投影分别有 ref/hash/coverage。

### 5.3 结算投影示例（提案；JSON 结构不改原卡）

```json
{
  "schema": "knowledge-contribution/v1",
  "contribution_id": "contribution_example",
  "run_id": "run_example",
  "task_id": "task_example",
  "terminal_event_ref": "event:terminal_example",
  "revision": 1,
  "supersedes": null,
  "task_outcome": "success",
  "contribution_state": "partial",
  "use_refs": ["usage:example"],
  "contributions": [{
    "subject_ref": "experience:example",
    "subject_hash": "sha256:example",
    "use_decision": "adapted",
    "declaration_authority": "model_declared",
    "helped": "unclear",
    "attribution_level": "insufficient",
    "evidence_refs": [],
    "missing_reason": "no_independent_contribution_evidence"
  }],
  "presented_without_declaration": ["method:example"],
  "projection_provenance_refs": ["event:retrieval_example"]
}
```

`helped=yes|no|unclear` 是证据支持程度下的贡献判断，`task_outcome` 是任务结果。收益级别分为 self_report / mechanism_supported / independently_compared / insufficient。反事实 `would_retry_without` 如未有对照只能标“模型估计”，不能进入实测节省量。

“未呈现”“已呈现未声明”“明确 not_applicable”“明确 rejected”分开。负向判断只从模型实际声明/独立标签取得，不为每个检索结果强制增加一次工具调用。

### 5.4 判断与对账最小字段

- 每个物理尝试：attempt_id、request_hash、questions_map_hash、排队/发出/结束时间、HTTP/transport 状态、usage、费用来源和 unknown。
- 每个逻辑题：question_instance_id、question_type、question_schema_version、options_hash、subject/context/extraction/template hash、答案分布、confidence、resolved_model、status。
- 判断不可变；对账记录单独追加，包含实际标签/来源/证据、blind_to_prediction、label_state=verified|unknown|disputed、label_revision；与既有provider reference材料分域。
- 只有标签充分且同一快照/版本才入准确率样本；缺失证据不能“回填 yes”。校准统计可重建，不用一个 `reconciled` 布尔值掩盖未评估与争议。

## 6. 六步闭环：入→存→取→用→结→调

### 6.1 入：保留教训优先，辅助检查不设新门

原 `save_experience` / `method_manage(save_candidate)` 继续按现有契约写入。Jev 缺失/超时/高置信冲突不能新增阻塞；原有 freshness/证据/权限校验不因 fail-open 被绕过。

去重/分类不是 Phase 0 必需项。后续可先在保存后的后台 shadow 检查；模型显式要求保存前辅助检查时才等待有界请求。

重复比较同时提供原始短片段、各自 ref/hash、环境/版本与抽取 coverage。“同根因”不意味着“相同机制或可安全合并”。只建议链接/复审；若主模型合并，须保留源 ref 与反例，不能静默覆盖。分类允许 other/unknown，分类标签是派生索引，不排除原检索。

### 6.2 存：不改主存储格式

沿用原文件/索引与 usage 账本。结构化前提先作 sidecar；抽取由模型产生或确认，程序只做结构/引用核验。原 scenario、全文与反例保持可回读。旧卡无需批量补字段才能继续使用。

### 6.3 取：先 shadow，后批准的有限排序试验

- 触发沿用实际工具调用，不新增 universal prompt 或每轮自动扫描。
- exact ref、rule、纯原文恢复路径不经过 Jev。
- shadow：只记录判断，现有排序/呈现不变；必须与 OFF 同样保留基线候选集。
- 排序试验：由模型/owner 显式选用，记录基线与实验顺序、实际呈现、恢复入口；不能默认静默全服务启用。
- Jev 只判断显式前提，不问整体“应否使用”；最后是否 adopt/adapt/reject 始终由主模型决定。
- 不再承诺“所有候选一次全文可见”：超物理预算时记录裁剪和 stable ref，compact cards 可发现、exact hydration 可恢复。

### 6.4 用：保留现有四态与负向语义

沿用原 `record_use`；不从调用序列推定已应用，不把没有回记当拒绝。仅机械观测 hydration 时仍标 `application_proven=false`；显式 applied/adapted 的 true 是窄义模型声明，不是独立应用/收益证明。

Rule 31 现有检索与评分义务仍有效。本设计不得为了增加评估覆盖而强制给所有候选补评分；需要策略变更时另交规则提案。

### 6.5 结：非阻塞、可恢复、有状态

优先以通用 `run.end` 的event identity建立“已记录结束事件”索引，再用knowledge.run_outcome、原usage与明确运行证据增强。它们不是业务成功标签；run.end没有run_ref的旧事件不按session强行关联使用声明，无匹配就产unknown/ambiguity。无knowledge tracker不伪造run_outcome；未结束/非正常退出单列既有恢复事实，多任务Goal只汇总，没有task_id不猜。

仅当批准自动持续处理、且实测证明当前源事件可靠性不足时，另提局部durable contribution intent或确认机制；不能把普通EventStore append的flush当fsync，也不能把迁移去重借给在线结算。显式中间评估形成partial revision，不算最终成功。

拟定状态：pending→building→complete / partial / needs_review；持久化失败记 storage_error，不能回执 complete。中断/取消保留真实 task_outcome=interrupted|cancelled|unknown，不改成 failed 或 success 来填分母。

- 程序可先汇总原账本；语义贡献初判复用已有授权的收尾/Reflection 结果，无结果则 unclear。
- 新增模型归因任务需要独立的资源范围，不能偷偷增加 foreground Provider 调用。
- 复用已有event identity/水位和SessionDigest currentness；新投影以 `(session_id, run_ref, event_type, knowledge_event_key/event_id, schema_version)` 区分业务身份，不能只靠同名key。持久去重、lease/重放仅对实证增量设计，不宣称在线exactly-once已具备。
- 告警看 eligible terminal 后超时的 backlog 年龄/数量、存储错误与覆盖率；原“连续 3 任务”只作补充，不能发现低流量长期卡住。
- 任务交付不等异步结算；现有原 usage 落账失败仍如实失败，不能因“投影可降级”改写原真相源契约。

### 6.6 调：生成建议，绝不自动施加质量判决

建议队列必须有 subject hash、适用范围、数据分母/区间、反例、建议理由及 expected revision。主模型可直接否决；获授权的无损修正按既有能力执行，越出权限才申请确认。所有生命周期变更走现有动作和回执。

取消原“引用≥5 且 helped<20%→失效”“90天零引用→归档”的准自动结论：少用可能是缺曝光或稀有场景，负面经验可能因成功避免事故而从不被 applied。安全教训和冷门反例保留独立复核入口。

现有 usage_net/threshold_alert 仍是机械汇总。新增实际收益/校准投影不得反向修改旧 ledger 或偷偷改 Rule 31 计分。

## 7. 前提、新鲜度、排序与探索

### 7.1 前提结构侧车（提议）

保留 `scenario: str`；新 sidecar 指向 exact subject ref/hash。最小字段为 extraction_state、extractor/model/template identity、source_spans/coverage、preconditions、counterexamples、freshness mapping。

preconditions 支持 required_all、required_any_group、optional；正文未声明必要条件时不强抽 required。允许空数组和 unstructured。各前提真假可原子判断，但整体适用性还依赖组合逻辑、反例与目的；Jev 拆题不会自动消除组合错误。

### 7.2 不采用原乘积公式

取消“前提满足率×confidence×method 0.8/experience 0.6×freshness”；这些系数无 LFL 数据依据，掩盖必要条件并惩罚未知。

初始 shadow 无排序公式。后续排序实验冻结一个简单、可解释策略：
- 原基线分数/顺序保留；semantic unknown、invalid、版本未资格通过时不改动。
- 仅在实际标签验证过的题型与范围内提出局部顺序建议，稳定 tie-break。
- required 前提 no、反例命中、来源冲突显示为建议证据；不能删除卡片或推成 Rule/权限判断。
- 具体重排幅度与展示预算作为独立实验参数预注册，不在本稿伪定“最佳”数值。

### 7.3 新鲜度与适用性分别呈现

已有版本指纹相等/不等由程序作机械事实；版本不等不等于内容错误，采集时间旧不等于过时。语义上的兼容性与当前任务适用性由模型核证；Jev 最多对给定证据输出建议。

freshness_refs 指向工具/代码/API 的当时证据，不能把外部判断覆盖写为 verified/current。缺依赖版本为 unverifiable，维持基线并提示，不数值化成 0.5。

### 7.4 探索针对曝光偏差，不针对“迫使采用”

全部候选已经可发现时，不重复注入低分项。仅在批准的有限展示试验中：
1. 基线候选池与实验池分别落 ref/hash，禁止覆盖候选原序。
2. 可用 10% 作为候选起点，绝非已资格参数；不得突破现有数量/字符预算。
3. 记录随机种子、抽样池、策略版本与进入展示的概率；去重，按可识别的独立实验组比较。
4. 若需挤占现有位置，先验证不会导致关键基线候选丢失；不能保证时保持 shadow 或独立基线组。
5. 旁路项 adopted/helped 只形成待复核偏差线索；只有原子前提独立反证才能称 Jev 错判。

删除“每200次必全量复查”：它既不是全库覆盖，也无流量/成本资格。改为预注册、分层的基线曝光审计。倾向校正只能用于被记录且有支持的抽样范围，不能外推整个语料库。

## 8. Jev 官方契约与调用边界

### 8.1 核实范围

【已核官方说明，非本机实测】截至审查日：
- TypeSafe 接口为 `POST https://api.typesafe.ai/v1/systemone`，Bearer 鉴权；请求核心为 model/state/questions，返回 model/answers/usage。
- 同一 state 可配多道独立命名题，支持 Choice/Score/Noul；逻辑原子问题不要求一次 HTTP 只问一题。
- Choice 返回选项及概率分布；confidence 是分布的确定性摘要，不能直接当“本系统命中概率”。Noul 没有同名 confidence。
- 官方模型页列 `jev-1.13.0`；alias 可能漂移，应绑定响应的 resolved model。容量与限流须按当前官方页和账户再核，不能写死为本机性能事实。

来源见附录 C。94.7% 单点准确率、月更节奏和 P95<2s 不作为本设计资格输入。

### 8.2 最小 wire 示例

这是官方字段形态的设计示例，没有发送过请求；endpoint 需按实际签约服务确认，不采用第三方仿站端点。以下选项描述为本设计自定义判据。

```json
{
  "model": "jev-1.13.0",
  "state": {
    "task_snapshot": {"target_os": "linux", "source_ref": "evidence:example"},
    "subject_ref": "experience:example",
    "subject_hash": "sha256:example"
  },
  "questions": {
    "premise_os": {
      "type": "choice",
      "instructions": "根据给定 task_snapshot，判断目标系统为 Linux 的前提。",
      "criteria": {
        "yes": "明确证据支持此前提",
        "no": "明确证据反对此前提",
        "unknown": "证据缺失、歧义或冲突"
      }
    }
  }
}
```

响应规范化保留：resolved model、每题 choice/probabilities/confidence、usage 和物理尝试身份。不要求官方不存在的 evidence_span；若需证据定位另由模型/本地源引用取得，不能编造出处。

### 8.3 逐题与整批校验

检查逐题 key/type、answer∈options、概率有限且在[0,1]、完整概率键与和、confidence 范围、resolved model、transport/usage。数值容差由契约固定并测试。缺某题只使该题 invalid/missing，不把整批伪称全成功。

schema-invalid 题保留原无效事实和 null，不填 confidence=0.5；usage 缺失为 unknown，不能计0。语义 unknown 是合法选项，contract-invalid 是协议失败，二者统计分开。confidence 与 p_selected 分开存；校准优先检查完整概率分布。

### 8.4 调度与资源

- 原子题数、HTTP 批数、并发数分别限制；共享 state 的独立题可小批打包，依赖上游答案的题不得混称独立。
- 入库比较5个旧条目可能有5道查重题；分类 task-type 与环境应拆题，原“固定三问”不能覆盖真实数量。
- 复用既有 Provider/资源/优先级事实能力；adapter 位于中性 provider/knowledge 边界，不新建第二个未经结算的 HTTP 世界。
- 外发策略记录 max_requests、total input/output tokens、总费用上限、排队与请求 deadline、最大候选/前提数；上限值待有界资格方案确定。
- 2秒仅可作请求 timeout 的试验初值，不承诺总 P95；连接/排队/重放都计入 whole-run 成本。
- 首轮关闭 SDK 自动重试；默认不重试。若获准重试，每个物理尝试独立落账、同一逻辑题关联，累计预算不能重置。
- 熔断按最小窗口样本数、transport/invalid/限流分项与恢复探针决定；小样本百分比不自动判高故障。
- 未知资源/发包结算边界先保持外发 OFF，不用“Jev 很便宜”代替授权与预算。

### 8.5 隐私、权限与恶意内容

外发只限实际获授权、所选题所需的受控投影；默认不发 Rules、完整会话、凭证、私有 reasoning 或跨 scope 源。脱敏不是“自由外发”的依据。

条目、网页和证据里的指令视为数据，不能授权 Jev 调工具、修改规则或指定动作。返回封闭选项只降低接口复杂度，不证明免疫 prompt injection；用恶意条目反例实测。Jev 不获 LFL 工具或资产写权限。

日志“全量”改为“逐次审计完整”：身份、状态、来源 hash、用量和必要结果完整；源正文按原作用域/保留期受控引用，不能无限复制敏感 payload。

## 9. 校准：独立标签先行，切换按证据

### 9.1 校准目标

`premise_check` 的 actual 是该时点/快照的前提事实；dup_check 的 actual 是定义明确的重复关系；不是 adopt、helped 或任务成功。

校准按 question_type、选项 schema、模板/抽取版本、resolved model、subject版本与必要任务分层。不能把稀疏桶都要求200条后造成无限等待；优先预注册主要范围，稀疏范围保持 shadow/insufficient。

标签来源含 objective_execution / independent_blind_model / human_review / host_self_report。首批盲评不见 Jev 答案、排序或建议；Jev 判据中的被测数字也不能泄露给参考标注者。分歧记 disputed，参考证据不足记 unknown。不是换一个模型就自动“独立正确”。

### 9.2 度量与样本选择

报告多类准确率/混淆矩阵、类条件漏判/误判、Brier、校准曲线与区间；unknown 既可作为合法参考标签，也要独立报告弃答/不可评估覆盖。不能只算高置信成功返回的准确率。

分母同时报告：eligible opportunities、attempted、transport-completed、schema-valid、independently-labelled、disputed、missing。timeout/取消/未对账均在覆盖与成本中可见。

相同任务多前提不是独立样本；按 task/run/模板来源分组划分训练校准与验证，区间按任务聚类估计。冻结测试集不可用于调阈值后再宣称独立通过。每主要题型200条只能作可行性起点，最终由效应大小/误判上限/区间精度确定。

### 9.3 版本漂移

请求钉版本、记录响应实际版本。未知新版本不得使用旧阈值。新版本只 shadow，固定基线与旧有效桶比较；旧模型不可调用时保留其历史证据和无 Jev 基线，不要求虚构双跑。

达到样本量、盲评质量和收益闸才讨论切换；“一周”“准确率不低于旧版2pp”本身不足。题型质量合格仍不能自动取得默认排序资格。发生漂移、误判集中或标签偏差时退 shadow，不自动改 Rules/内容。

## 10. 指标：以结果和返工为主

| 指标 | 分母/口径 | 用途 |
|---|---|---|
| 任务验证成功率/FCR | 全部预注册有效任务；首轮成功与最终成功分开 | 主指标；不得为采用率牺牲正确率 |
| 错误重试/返工 | 每任务，有执行事实的 ordinary/target retry 与改写分开 | 优先收益；未知归因单列 |
| whole-run wire/现金/时延 | 主模型+Jev+归因任务+全部物理重试；usage unknown 单列 | 总成本；工具次数只作诊断 |
| 召回/曝光/水合/声明 | 各链路有自己的分母，provider-visible 与 rendered 分开 | 找闭环断点；不把声明增量当收益 |
| 结算覆盖/延迟/积压 | eligible terminal 且超过约定 grace 的任务；取消/中断分项 | 管道健康；partial 不冒充 complete |
| actual 标签覆盖与独立性 | 全部可评估逻辑题；标签来源、争议、盲化比例 | 防自证与选择偏差 |
| 必要前提错判/类条件漏判 | 冻结题型/类别，有独立事实标签 | 高风险限制；总体准确率不能掩盖它 |
| 恢复与越权 | exact ref恢复成功、分页前进、rule/scope外发与状态误变计数 | 必须零未授权变更；不能只看检索成功 |

取消“top3 采用率+10pp”上线指标；它可被排序暗示提高。取消“回填率≥60%即达标”的单一门：更高回填不证明标签更可靠。任何数值目标在实际任务规模/基线/业务风险核定后预注册，不能观察完结果再改闸。

## 11. 分阶段实施与停止条件

| 阶段 | 最小改动/交付 | 验收 | 停止/回滚 |
|---|---|---|---|
| P0a 剩余关联/覆盖审计 | 静态映射与完整分段计数已完成；走EventStore/SessionDigest，对declared-use、hydration、prepared和open/interruption分层核身份/coverage | 同服务/时间窗/机会分母；run.end无run_ref时不强join；稀薄类别不足与源码bug分开 | 不开新采样、不补造终态；不改producer或外发 |
| P0b 复用链的只读贡献投影 | 现有EventStore/SessionDigest+usage；先一条run投影和unknown报告；只补已证实缺字段，不默认新journal/worker | 正常/多任务/中断/重放；零原账本写入、零重复评分；需新增持久处理时才验证崩溃/并发 | 停增量投影，不关闭既有知识观察；保留原账本与现有canary契约 |
| P1a 本地 fixture + shadow 方案 | **已实现（2026-10-15，v0.7）**：`src/llm_loop/knowledge/jev/`（wire/policy/transport-mock/shadow）+ 冻结盲评集 `tests/fixtures/jev/blind_eval_v1/`；88 定向测试；代码闸三轮回执 `data/audit/code_gates/RULE-AI-28-jev-p1a-20261015.md`；未接入 live 检索路径 | 零真实外发：包内无网络 import（tripwire+测试守卫）、仅 Mock 传输、transport 必须显式注入；OFF/shadow 输出一致：runner 无候选集/排序 API 面、事件 ordering_effect=none、src 无包外接线；negative cases：wire 12 类 + 预算 4 类 + 守卫 25+ 例 + 传输/事件故障 | 维持 OFF：无新增开关；真实传输属 P1b 另授权 |
| P1b 有界外部 shadow（另授权） | **参数已预注册冻结（§11.1，v0.8）**：固定模型/用途/scope/任务集；独立 actual 标签已备（blind_eval_v1 独立盲评，附录 C v0.7→v0.8）、成本与对账报告；**OpenRouter 分支预注册 §11.6（v0.8.7）**：TypeSafe 官方凭据未取得，endpoint/凭据名/模型 id/resolved 合法集四字段经新一轮预注册变更，其余沿用；**R1 已执行：6/6 contract_invalid（官方 wire 字段名 `choice` vs 实现误读 `answer`，预算 2/2 用尽零重发；附录 C v0.8.8）**；**§11.7（v0.8.9）R4 修复轮预注册冻结：契约符合性修复（三验证器官方字段名+noul 值域+answers 摘录），代码闸 REVISE→PASS，manifest 重冻 cases/labels 字节不变，预算/任务集/标签源/对账全部沿用；**已执行（13:18）：6/6 valid、6/6 与冻结标签一致（附录 C v0.8.9）** | 不改排序/保存；按类质量与未知比例可审计；API可用≠效果通过；观察结果后改闸属违规，需新一轮预注册 | 超预算、泄露、版本漂移、隐式重试即停 |
| P1b-L 本地开源 judge 影子（用户 2026-10-15 10:35 指示） | **参数已预注册冻结（§11.2，v0.8.2）**：SemIf+Qwen3.5-4B@851bf6e+MLX 本地评分（shared 模式），零外发、零凭据、零费用；任务集/标签源/对账口径同 §11.1/§11.1.1 | 不构成 Jev 校准资格（SemIf 复现接口模式而非 Jev 本体）；6 题仅为链路验证与本地 judge 单批次事实；观察结果后改闸违规 | 评分进程超时/异常退出、manifest SHA 漂移、守卫命中、resolved_model 漂移即停 |
| P1b-L2 本地 judge 扩样（用户 2026-10-15 11:03 指示） | **参数已预注册冻结（§11.3，v0.8.3）**：blind_eval_v2 44 题（manifest SHA `60a17edf…`）；judge/传输同 §11.2 不变；双源独立盲评（glm-5.3-flash+deepseek-v4-flash）先于评分；分桶对账 | 44 题 <§9.2 200 条可行性起点：不构成校准/Jev 校准/排序资格；观察结果后改闸违规 | §11.3 中止条件全部沿用；另加预运行闸：双源一致率 <70% 即 `label_insufficient` 暂停 |
| P2a 单变量排序试验（另决策） | 冻结策略、基线组、有限曝光审计、模型绕过出口 | 成功率不退化；返工或全任务成本有可重复改善；关键候选恢复验证 | 恢复原顺序/停调度，不删资产 |
| P2b 去重/分类与建议队列 | 各用途独立 shadow/收益资格、带版本复审建议 | 无静默合并/删除/状态变化；原/新版本证据保全 | 停该用途并隔离派生结果 |

### 11.1 P1b 参数预注册（冻结于任何真实外发之前；v0.8）

依据 §10“任何数值目标……预注册，不能观察完结果再改闸”与 §9.1 冻结流程，以下参数在获得 P1b 外发授权之前冻结；授权后不得改闸再跑，观察结果后改闸属违规（需新一轮预注册）。

| 维度 | 冻结值 |
|---|---|
| 固定模型 | `jev-1.13.0`；每响应绑定 resolved model，≠`jev-1.13.0` 即版本漂移，按 §9.3 停止并退 HOLD |
| 单一用途 | 仅 `premise_check` 题型（choice yes/no/unknown）。dup_check、coverage_score、分类、noul 题一律不进 P1b |
| 任务集 | 冻结 `tests/fixtures/jev/blind_eval_v1/`（manifest SHA-256 `2fc40cfa4226b5c5024c0a874b7ca6168202cbf8a671abe6efdd7476cba8227d`）中 premise 类 6 题：case-001/002/003/006 的 `premise_linux` + case-004 的 `premise_bare_metal`/`premise_systemd`。case-005（dup）/007（score）/008（noul）按单一用途排除 |
| 预算上限 | HTTP 批数 ≤2（6 题按每批 ≤5 题打包）；每请求 input ≤2000 tokens、output ≤2000 tokens（policy.py 试验初值转正式冻结值，撤销 provisional）；重试 0（隐式/显式均关）；单请求 deadline 2s；本批 6 题/2 请求为总量上限，不追加；费用以响应 usage 如实记录，缺失记 unknown 不计 0 |
| 对账口径 | 标签源=独立盲评结果（`outputs/jev-blind-eval-20261015/blind_eval_result.json`：judge=deepseek/deepseek-v4-pro 隔离子代理、零上下文继承、0 工具调用；与作者标签 9/9 取值一致，premise 子集 6/6 verified）；逐题 confusion（yes/no/unknown 三类）+ 弃答/schema-invalid 单列，分母含 eligible/attempted/transport-completed/schema-valid/labelled/missing 全链（§9.2）；样本量 6 仅证明 wire/守卫/对账链路可运行，**不构成 §9.2 校准资格**（200 条可行性起点远未达） |
| 中止条件 | 任一即停并退 HOLD：任一预算面超限；守卫触发（红线键/凭证样式/工具授权字段任何命中）；resolved model 漂移；出现隐式重试；任一题 schema-invalid 且原因未明 |
| 闸序 | 本节冻结先于授权与任何外发；结果观察只产生报告，不回改本节 |

### 11.1.1 预执行增补（v0.8.1；生效于任何真实外发之前）

本增补按用户 2026-10-15 09:51 指令在首次真实外发前冻结；此前零真实外发（P1a 验收事实不变），故不属“观察结果后改闸”。生效后与 §11.1 主表同等冻结，改任一字段需新一轮预注册。

| 项 | 增补内容 |
|---|---|
| 授权记录 | 用户 2026-10-15 09:51（Asia/Shanghai）：授权本批次真实外发——6 题/≤2 请求，费用上限 10 元 RMB；确认 endpoint/账户（官方 `POST https://api.typesafe.ai/v1/systemone`）；指令 judge 不得用 deepseek-v4-pro，改用 glm-5.3-flash 或 deepseek-v4-flash |
| 对账口径·标签源替换 | v1 盲评（deepseek-v4-pro）弃用作 P1b 标签源，保留为历史；生效标签源 `outputs/jev-blind-eval-20261015/blind_eval_result_v2_ds_v4_flash.json`：judge=deepseek/deepseek-v4-flash 隔离子代理（零上下文继承；requires tools=[]/network=false/fs=false；回执 tools=0，tokens 15417/3670）；与作者标签 9/9 取值一致，premise 子集 6/6 verified；case-005 维持 disputed、case-007 维持 unknown（不因一致升级）；注入反例按数据处理。其余对账口径不变 |
| 费用上限执行口径 | cost_cap=10.0 元 RMB（收紧，非放宽）。无官方价目表不可事前精确折算，执行面为三层：(a) 冻结 token 硬闸（HTTP≤2、每批题≤5、est input≤2000/output≤2000 累计、重试 0、deadline 2s）；(b) 响应 usage 如实入账；(c) 响应若携带费用字段且累计>10 元即中止剩余批次并记 budget_breach；费用缺失记 unknown 不计 0 |
| 批次打包（固定） | batch-1 = case-001/002/003/006 的 `premise_linux` ×4：共享 state（四案例快照按 case 键内联），每题 instruction 显式限定仅依据本题所属快照——跨案例同 state 是打包事实，如实入报告；batch-2 = case-004 的 `premise_bare_metal`+`premise_systemd` ×2（单 subject state）。题目名带 case 后缀以保唯一 |
| 前置条件 | 真实传输需 `TYPESAFE_API_KEY`；2026-10-15 09:20 复核 .env 无任何 TypeSafe 凭据（仅 DEEPSEEK/EMBEDDING/FEISHU/FUYAO/GLM/LLM/MINIMAX 七类凭据名）。凭据未就位即不发送；不得以其它 provider 凭据替代（跨方泄露）。真实传输实现置于包外 runner（`outputs/jev-p1b-20261015/`），jev 包内零网络 import tripwire 维持 |

P1b 通过不授予排序资格：§9.3 的样本量、盲评质量与收益闸（P2a 前置）不变；收益归因另依赖 producer 机会分母字段（附录 C v0.7→v0.8 第 3 条）。

### 11.2 P1b-L 本地开源 judge 影子预注册（新一轮；冻结于任何本地真实评分之前；v0.8.2）

依据 §11.1.1"改任一字段需新一轮预注册"，本节为**新一轮预注册**：不修改 §11.1/§11.1.1 任何冻结字段（TypeSafe 真实外发路径原样保留，待 TYPESAFE_API_KEY 就位后按其原冻结值执行）。触发：用户 2026-10-15 10:35 指示"网上有类似 jev 的开源模型可以替代，可以本地部署"+10:40 提供来源（二手文，仅作线索）。截至本节冻结时点：零真实外发（P1a 验收事实不变）；P1b 仅完成 mock dry-run，其答案为脚本中立值、不构成对任何 judge 质量的观察——故本节属"先冻结后执行"，非"观察结果后改闸"。

【已核一手事实】SemIf（`github.com/TheoLeeCJ/SemIf`，MIT，原 OpenJev）：开源复现 Jev 接口模式（state + 结构化 options 进、各选项概率出；直接读 option 概率、无文本生成），原生 MLX 后端（Apple Silicon），冻结基线 `Qwen/Qwen3.5-4B@851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`，shared 模式 = 一次 state prefill + 独立题后缀（要求全批同 state）。其自述：复现的是接口模式，不复现 Jev 未公开的模型与训练；与 TypeSafe 无关。另一手核实：Jev 1.13 已上架 OpenRouter（`typesafe/jev-1.13`，Decisions API）——保留为真 Jev 校准备选路径，本轮不使用。第三方跑分（含 SemIf 73.1→47.7 排名波动）不作为本设计任何资格输入。

| 维度 | 冻结值 |
|---|---|
| judge 主体 | vendored SemIf（master tarball，`outputs/jev-p1b-20261015/vendor/SemIf`，py3.11 venv，mlx 0.32.2）+ `Qwen/Qwen3.5-4B@851bf6e…` + MLX 后端、源精度 bf16 不量化 + shared 模式。resolved_model 固定 `semif-phase1+Qwen3.5-4B@851bf6e+mlx`，漂移即停 |
| 替代声明 | 本批结果 = 本地开源 judge（接口模式复现）单批次事实；**不构成 Jev 校准资格**，也不构成 §9.2 校准资格（6 题）；Jev 主线不变 |
| 单一用途/任务集/打包 | 同 §11.1/§11.1.1：仅 premise_check 6 题；manifest SHA `2fc40cfa…` 不变；批1（4 题同 state）+ 批2（2 题同 state），满足 shared 同 state 约束 |
| 传输 | 本机 subprocess 调 vendored venv（包外 `local_semif_transport.py`；jev 包内零网络 tripwire 维持）；零外发、零凭据、零费用；§11.1.1 的 10 元费用上限未被使用（本地无计费面），不重释为已花额度 |
| 预算 | 评分进程调用 ≤2（每批一次）；重试 0；单次 deadline 180s（实测装载+shared 首评分 ~9s，冻 180s 为安全裕量，观察后不改）；Jev usage 字段记 unknown 不计 0（本地无计费计量，不虚构）；SemIf 逐题 input_tokens/forward_seconds 落盘 `semif_audit/` 供审计 |
| 映射契约 | question=instructions（含 case 专属限定语）；options=yes/no/unknown（description=criteria 对应项）；answer=argmax；probabilities=dict(zip(option_ids, softmax 数组))——SemIf 输出为按选项顺序的数组而非字典（已核源码 direct.py/shared.py），adapter 负责转换；confidence:=p_selected（SemIf 无 Jev confidence 字段，此为 adapter 定义的分布确定性摘要；两者分字段存）；SemIf 自带 `probability_status="conditional option score; uncalibrated as decision confidence"` 原样入审计与报告，不作校准解读 |
| 对账 | 标签源不变（§11.1.1 生效版 `blind_eval_result_v2_ds_v4_flash.json`）；逐题 confusion + §9.2 全链分母同 §11.1 |
| 盲性 | judge（本地权重 SemIf+Qwen3.5-4B）与 labeler（deepseek-v4-flash，远程 API）不同实现、不同运行面；fixture labels 文件不进入 judge 输入（runner 仅读 cases/wire_examples，P1a 机械隔离保持）；部署冒烟仅用 SemIf 自带示例与自造题，不含冻结 6 题任何一题 |
| 中止条件 | 任一即停并如实记录：manifest SHA 漂移；守卫命中；shared 模式 state 不一致（评分层拒绝）；评分进程超时/非零退出；任一题 schema-invalid 且原因未明 |
| 冒烟证据（冻结前取得，非冻结 6 题） | SemIf 官方 examples 各行 state 不同被 shared 拒绝（约束生效佐证）；自造同 state 2 题：platform=linux→yes 0.999、"version 恰为 3.10？"（实为 3.11）→no 0.588；单进程含装载 ~8.7s |

### 11.3 P1b-L2 本地 judge 扩样预注册（新一轮；冻结于任何 v2 本地评分之前；v0.8.3）

依据 §11.2 同构纪律：本节不修改 §11.1/§11.1.1/§11.2 任何冻结字段。触发：用户 2026-10-15 11:03 选定"①本地 judge 扩样（预注册新轮，premise_check 扩到 30-50 题，本地零成本）"。截至本节冻结时点：blind_eval_v2 已构建并冻结 manifest（SHA-256 `60a17edf43de07b189ee28ecb27bbbfd6a11003629bc42b9c2215d6e68d4b97e`）；v2 集任何一题未经任何 judge 评分；双源盲评未开始。v1 六题首跑结果（5/6）仅用于失败形态分桶设计（case-003 no→unknown 漏判、case-006 低确定命中），属诊断性分层而非闸值调优——本轮不含任何资格阈值。

| 维度 | 冻结值 |
|---|---|
| judge 主体/传输 | 与 §11.2 完全一致（vendored SemIf + `Qwen/Qwen3.5-4B@851bf6e…` + MLX bf16 + shared 模式；resolved_model `semif-phase1+Qwen3.5-4B@851bf6e+mlx` 漂移即停；包外 `local_semif_transport.py` 复用不改） |
| 任务集 | 冻结 `tests/fixtures/jev/blind_eval_v2/`：13 案例 / 44 题（作者标签分布 yes19/no14/unknown11，仅构造分层用）；仅 premise_check choice yes/no/unknown；judge 可见面不含 `labels/` |
| 打包 | 每 case 一批（state=该 case 快照，批内题数 ≤5）：共 13 批；无跨 case 共享 state |
| 预算 | 评分进程调用 ≤13（每批一次）；重试 0；单次 deadline 180s（§11.2 冻结值沿用）；est input ≤2000 tokens/请求；本地零费用（§11.1.1 的 10 元额度仍不使用、不重释） |
| 标签源 | 双源独立盲评：`glm-5.3-flash` 与 `deepseek-v4-flash` 各一隔离子代理（用户 2026-10-15 09:51 已列名两者；零上下文继承；tools=[]/network=false/fs=false；输入=13 案例快照+题目 instructions+criteria，对称于 judge 可见面；不见作者标签/他源标签/judge 输出）。合并规则：两源取值一致→`dual_agreed`（入准确率分母）；不一致→`disputed`（出准确率、单列计数，不以作者标签仲裁）；任一缺→`missing`。诚实边界：glm-5.3-flash 与作者会话模型同家族（glm-5.3），独立性弱于两源均异家族；机制隔离（零上下文继承+标签不入输入）保持 |
| 预运行闸 | 双源一致率（dual_agreed/44）<70% → 标签不足，暂停评分（`label_insufficient`），不跑批 |
| 对账口径 | 准确率/三类混淆矩阵仅在 dual_agreed 子集；类条件漏判单列（重点：no→unknown，case-003 形态）；p_selected 分箱 [0.5,0.6)/[0.6,0.7)/[0.7,0.8)/[0.8,0.9)/[0.9,1.0] 逐箱准确率（p_selected 为 adapter 定义的分布确定性摘要，SemIf 自带 uncalibrated 声明沿用）；注入桶（case-105/106 中注入文本在场的 4 道语义判定题）单列；低确定命中（p_selected<0.6 且答对）与低确定错判单列；§9.2 全链分母（eligible 44 / attempted 13 / transport-completed / schema-valid / dual-labelled / disputed / missing） |
| 主张边界 | 44 题（dual_agreed 子集 ≤44）仍低于 §9.2 每主要题型 200 条可行性起点：不构成校准资格、不构成 Jev 校准、不授予排序/保存/生产资格；结果为本地 judge 扩样单批次事实 |
| 中止条件 | 任一即停并如实记录：manifest SHA 漂移；守卫命中；评分进程超时/非零退出；shared state 不一致被拒；任一题 schema-invalid 且原因未明；预运行闸 `label_insufficient` |

### 11.4 P1b-L2-R2 扩样轮重预注册（direct 模式；冻结于任何 v2 direct 评分之前；v0.8.4）

**触发与 §11.3 轮中止事实**：§11.3 轮于 2026-10-15 11:19:51 启动，13 批计划；批1（case-101，4 题）recorded（3 道 dual_agreed 全中，1 道 disputed 不入分母）；批2（case-102）评分进程 exit=1：`ValueError: The fixed state prefix does not match every full prompt`（SemIf `shared.py::_check_prefix`）→ 按 §11.3 冻结中止条件"评分进程异常退出"停轮，剩余 11 批未跑。回执：`outputs/jev-p1l-expand-20261015/{p1l_expand_report.json, jev_shadow_events_v2.jsonl, semif_audit/}`。

**根因（已核 vendored 源码）**：shared 模式的 state 前缀由"占位题"探针渲染 chat template 后取证据序列化并去尾 token 编码；state JSON 与题目后缀在分词边界存在融合可能，融合与否随题目首字符变化——批内题目不一致即整批抛错。v1 六题首跑与 case-101 批通过属边界兼容的偶然，不是协议保证。**任何在 shared 约束下"调题目措辞以过前缀校验"的做法都会改动冻结任务集，禁止。**

**唯一变更面**：`--mode shared → direct`。CLI direct 模式对每行（每题）独立全前向评分、无前缀校验；prompt 构造（`direct.py::encode_prompt`→`direct_messages`）与最后位 logits→softmax 数学与 shared 完全同路径（同一 `_result`），仅无前缀缓存复用。resolved_model 记 `semif-phase1+Qwen3.5-4B@851bf6e+mlx-direct`（模式显式入 ID）。新传输件 `outputs/jev-p1l-expand-20261015/local_semif_transport_direct.py`（子类化，不改 §11.2 冻结件）。

**不变项（全部沿用 §11.3 冻结值）**：任务集与 manifest（SHA `60a17edf…`）；打包（每 case 一批、≤5 题/批、共 13 次评分进程调用）；deadline 180s/次；重试 0；est input ≤2000 tokens/请求；本地零费用；双源盲评结果与合并规则（dual_agreed 43 / disputed 1 已冻结落盘，预运行闸 97.7% 已过）；对账口径（分箱/注入桶/低确定/no→unknown/全链分母）与主张边界不变。

**已见题处理（诚实分桶）**：case-101 的 4 题在 §11.3 轮已被 judge（shared 模式）评分，从本轮主指标剔除；本轮仍对其实施 direct 评分，仅作 shared↔direct 同题执行一致性观察（`seen_bucket`，不入任何准确率）。主指标集 = cases 102–113 的 40 题（全部 dual_agreed；唯一 disputed 属 case-101）。

**冻结时序**：本节写入时，direct 模式尚未对 blind_eval_v2 任何一题执行过。中止条件沿用 §11.3（"shared state 不一致被拒"一条随模式更换自然失效）。

### 11.5 P1b-L2-R3 扩样轮重预注册（预算记账修正；冻结于 R3 任何评分之前；v0.8.5）

**触发与 R2 中止事实**：§11.4 轮（run_ref `p1l2-20261015-expand02-direct`）于 2026-10-15 11:25 执行：批1 case-101 recorded（seen_bucket，direct 与 §11.3 shared 答案 4/4 一致）；批2 case-102 recorded（3 道 dual_agreed 全中）；批3 case-103 被守卫 `BudgetRefused: output_tokens_over_cap` 拒绝 → 按冻结中止条件停轮。回执：`p1l_expand_report_direct.json`、`jev_shadow_events_v2direct.jsonl`、`semif_audit_direct/`。

**根因（已核 policy.py 与事件 facts）**：守卫对每题按 est_output_tokens=256 固定估算累计记账；§11.3/§11.4 沿用 v1 的 max_output_tokens=2000 总上限（v1 仅 6 题 ×256=1536 故通过），与 44 题任务集（44×256=11264）在算术上不相容。同法核出 est input 亦为累计口径（44 题估 ~3900 > 2000 上限），为同类潜在中止点。两上限均为机械记账边界，非资格/阈值参数。

**唯一变更面**：`max_output_tokens 2000→12288`、`max_input_tokens 2000→8000`（est 全量核算：output 11264/12288、input ~3900/8000、requests 13/13、q/批 ≤5/5、deadline 180s/次实测 ~8s）。其余一切沿用 §11.4 冻结值。

**已见题处理（诚实分桶扩大）**：case-101（§11.3 shared + R2 direct 两轮暴露）、case-102（R2 direct 一轮暴露）共 7 题全部转入 seen_bucket，不入任何准确率；本轮仍对全部 13 批评分（同 prompt 确定性复算），seen_bucket 对照 R2 答案作执行一致性观察。**主指标集 = cases 103–113 的 33 题**（全部 dual_agreed）。

**追加中止规则**：若 R3 仍因预算/记账类原因中止，停止逐轮补丁，先离线核算全部守卫约束与 13 批计划的全量边界，再议 R4——不允许"逐轮发现逐轮改"。冻结时序：本节写入时 R3 未执行。

### 11.6 P1b-OR OpenRouter 分支预注册（新一轮；冻结于任何 OpenRouter 真实外发之前；v0.8.7）

**触发与前置事实**：用户 2026-10-15 11:58 报告已取得 OpenRouter key、12:04 写入根 `.env`（`OPENROUTER_API_KEY`；已核存在性/格式：单条、73 字符、`sk-or-` 前缀、无引号/空格；key 值不进入任何输出/记录/文档）。§11.1.1 前置的 `TYPESAFE_API_KEY` 至今未取得（09:20 复核无 TypeSafe 凭据），TypeSafe 官方路径原样保留待未来凭据。依据 §11.1.1"改任一字段需新一轮预注册"，本节为**新一轮预注册**：不修改 §11.1/§11.1.1 任何冻结文本；仅变更四个传输面字段并预注册一项预检，其余全部沿用。

【已核一手事实（2026-10-15 12:04–12:10，公开页面/端点 API，未携带 key、未调用任何 judge、未发送任务数据）】：
- OpenRouter Jev guide（`/docs/guides/community/jev`）：Jev 暴露于两个 surface——Decisions API `POST https://openrouter.ai/api/alpha/decisions`（通用 HTTP/SDK）与 System One API `POST https://openrouter.ai/api/v1/systemone`（TypeSafe SDK 换 base URL 即用）；两 surface 同 key、同账户计费；每个响应含 `usage.cost`（USD）；context 262,144 tokens（state+questions）。
- Jev tutorial：curl 示例 body 为 `{"model": "typesafe/jev-1.13", "state": {...}, "questions": {...}}`，鉴权 `Authorization: Bearer $OPENROUTER_API_KEY`——与 §8.2 冻结 wire 形态逐字段一致。
- per-model endpoints API（`/api/v1/models/typesafe/jev-1.13/endpoints`）：`typesafe/jev-1.13` 存在，唯一 endpoint 快照 `typesafe/jev-1.13-20260917`，pricing prompt $0.000000042/token、completion $0，uptime 正常。
- 版本页 `/typesafe/jev`：家族已出现 `typesafe/jev-1.14`（快照 20261014）；本分支钉 1.13 别名不受影响。`/api/v1/models` 公共列表当前仅返回 `typesafe/jev-router`（text→text 路由变体，非 Decisions 形态），不采用；模型存在性以 per-model endpoints API 与模型页（均 200）为准。
- 模型页 drop-in code 为客户端渲染（`BAILOUT_TO_CLIENT_SIDE_RENDERING`）——上午静态抓取失败的原因；等价 wire 事实已从 guide/tutorial 静态正文取得。
- 预检端点：`GET /api/v1/auth/check` 404 不存在；`GET /api/v1/key` 无 key 探测 401（存在且要求鉴权）。

| 维度 | 冻结值 |
|---|---|
| endpoint | `POST https://openrouter.ai/api/v1/systemone`（System One surface：与 §8.2 冻结请求形态 model/state/questions 进、model/answers/usage 出一致）。换用 `/api/alpha/decisions` surface 或任何其它端点属新一轮预注册，不得运行中切换 |
| 凭据 | 根 `.env` 的 `OPENROUTER_API_KEY`（runner 从 .env 定向读取该单键，不经 shell history/export）；不得以其它 provider 凭据替代；key 值不写入任何报告/事件/文档 |
| 模型 id（请求） | `typesafe/jev-1.13`（OpenRouter 命名空间；§11.1 `jev-1.13.0` 的 OpenRouter 别名）。**resolved model 漂移条款**：响应 `model` ∈ {`typesafe/jev-1.13`, `typesafe/jev-1.13-20260917`}（别名及其当前唯一 endpoint 快照，2026-10-15 读数）为合法；其它任何值（含 1.14、router、无命名空间形式）即版本漂移，按 §9.3 停止退 HOLD |
| 预检（新增） | 发题前允许 1 次 `GET https://openrouter.ai/api/v1/key`（仅验 key 有效性；0 题、0 模型调用、不发送任务数据）；非 200 即停，不发第一批。此调用不占用也不计入 ≤2 请求批预算，单列记账 |
| 费用口径 | 记录用牌价：prompt $4.2e-8/token、completion $0（endpoints API 读数）；硬闸仍为 §11.1.1 三层（token 四面冻结值 + 响应 usage/cost 如实入账 + cost 字段累计 >10 元 RMB 即中止并记 budget_breach）；USD 原值入账，缺失记 unknown 不计 0 |
| 其余全部沿用 §11.1/§11.1.1 | 单一用途仅 premise_check；任务集 manifest SHA `2fc40cfa…` 6 题；HTTP ≤2、每批题 ≤5、input/output ≤2000 tokens、重试 0（隐式/显式均关）、单请求 deadline 2s、总量 6 题/2 请求封顶；标签源 `blind_eval_result_v2_ds_v4_flash.json`；§9.2 全链分母对账；中止条件全文沿用（超预算/守卫命中/resolved model 漂移/隐式重试/任一题 schema-invalid 原因未明） |

**诚实边界**：本节冻结时点，OpenRouter 路径零真实外发、零 judge 调用（上述核验均为无 key 公开读取）；本节未参考任何 OpenRouter 实测结果。deadline 2s 沿用 TypeSafe 冻结值——OpenRouter 含路由层可能更慢，超时即按中止条件停轮并如实记录，不得据此放宽（放宽属新一轮预注册）。P1b-OR 通过仍不授予排序/保存资格（§9.3 与 P2a 前置不变）；本批 6 题仅证明 wire/守卫/对账链路在 OpenRouter 面可运行，不构成 §9.2 校准资格。

### 11.7 P1b-OR R4 修复轮重预注册（官方字段名修复；冻结于任何 R4 真实外发之前；v0.8.9）

**触发与 R1 中止事实**：§11.6 轮于 2026-10-15 12:16:59–12:17:01 执行（run_ref `p1b-or-20261015-batch01`）：预检通过、预算合规（2/2 请求、6/6 题、input 1952/output 269、零重试、无漂移），但 **6/6 题 contract_invalid、valid_q=0、无对账可做**。根因（附录 C v0.8.8，三方证据）：官方逐题值字段为 `choice`（同族 score/noul），wire.py 三验证器自 P1a 起误读自造 `answer` 键；Mock 与 fixture 共享同一误读故定向测试全绿；原始响应仅存 hash 未留档，choice 值不可事后恢复。

**用户授权**：2026-10-15 12:29 "修"——授权修复+代码闸+预注册+同任务集重跑（2 请求/6 题，预算同冻结值）。

**唯一变更面（契约符合性修复，非结果驱动）**：
1. `wire.py` 三验证器改官方字段名（choice/score/noul）；noul 按官方 [0,1] 数值契约执行（`_finite_in_unit`，含 bool 陷阱）；invalid 原因串 `choice_not_in_options`/`noul_out_of_unit_or_not_finite`。设计 §8.2 原文本即写 `choice`，本修复使实现回到设计，不构成设计变更。
2. `shadow.py`：任一题非 valid 或批级无效时，事件 payload 与 outcome 持久化官方 answers 原文摘录（`RAW_ANSWERS_EXCERPT_CAP=4096`，超出截断并标注）——R1 教训"raw 丢弃即不可诊断"的机制性补丁；全 valid 不复制 payload。
3. fixtures `wire_examples/` 8 样本改官方字段名（`invalid_answer_not_in_options.json` 更名 `invalid_choice_not_in_options.json`；noul 样本值改数值 0.42）；**manifest 重冻 SHA-256 `4372a1885adb83cbbfd9156c2b3da5680b9b631d2ee8aed49d050181a2364636`**——被判定面零变更：`cases/` 六题文件与 `labels/` 字节不变（SHA 逐一核对），六题的快照/instructions/判据与 §11.1 冻结任务集逐字节相同；变更仅 wire 契约测试样本与 manifest 包装。
4. 包外：`local_semif_transport.py` 同步 choice 键（防 local 路径复现根因）；`run_batch.py` manifest SHA 常量更新、mock 官方键、run_ref 加 `-r4` 后缀、real_or 报告改写 `p1b_or_report_r4.json`（**R1 报告 `p1b_or_report.json` 原样保留**）、报告 entry 增摘录字段。

**代码闸**：两轮（REVISE 4×P2→处置→复核 PASS），回执 `data/audit/code_gates/RULE-AI-28-jev-wire-official-fields-20261015.md`（含修复后各文件 sha256、TDD RED 12 failed→GREEN、定向 97 passed、ruff 全过、全量回归记录）。终态 sha256：wire.py `2057279b…`、shadow.py `61a2610a…`、run_batch.py `10720684…`、local_semif_transport.py `b0450248…`。

**不改项（全部沿用 §11.1/§11.1.1/§11.6 冻结值）**：endpoint `POST https://openrouter.ai/api/v1/systemone`；凭据 `OPENROUTER_API_KEY`（值不入记录）；模型 id `typesafe/jev-1.13` 与 resolved 合法集 {`typesafe/jev-1.13`, `typesafe/jev-1.13-20260917`}；预检 1 次 `GET /api/v1/key` 单列记账；单一用途仅 premise_check；任务集六题（内容字节不变，见上 3）；批打包 batch-1×4/batch-2×2（§11.1.1）；预算四面 HTTP≤2、6 题、input/output ≤2000 est、重试 0、deadline 2s、总量封顶不追加；费用上限 10 元 RMB 三层执行口径与牌价记账；标签源 `blind_eval_result_v2_ds_v4_flash.json` 不变；§9.2 全链分母对账；中止条件全文沿用（超预算/守卫命中/resolved model 漂移/隐式重试/任一题 schema-invalid 原因未明）。

**为何不属"观察结果后改闸"（诚实边界）**：R1 未产生任何判定值观察——choice 被丢弃、raw 未留档、valid_q=0、无对账发生；本节不含任何质量/阈值/统计参数；修复对象是"实现对官方契约的符合性"，R1 的唯一"观察"是协议解析失败本身。同型先例：§11.4（shared 前缀校验缺陷→direct 模式）、§11.5（预算记账算术不相容→上限修正），均为中止后的契约/机械修复轮。

**R4 执行口径**：mode=real_or，run_ref `p1b-or-20261015-batch01-r4`，报告 `outputs/jev-p1b-20261015/p1b_or_report_r4.json`，事件追加 `jev_shadow_events.jsonl`；结果只产报告与附录 C v0.8.9 记录，不回改本节；通过仍不授予排序/保存/校准资格（§9.3、P2a 前置不变）。

**已知缺口（记录不扩面）**：wire fixture 集无 score 型样本（choice×7+noul×1；score 契约由内联单测钉住）——留待未来重冻轮，不改变本轮冻结面。

### 11.8 P1b-OR-V2 v2 扩样对真 Jev 预注册（新一轮；冻结于任何 v2→OpenRouter 请求之前；v0.9）

依据 §11.1.1"改任一字段需新一轮预注册"，本节不修改 §11.1–§11.7 任何冻结文本。**触发与授权**：用户 2026-10-15 13:32 "1授权"——授权 blind_eval_v2 44 题对真 Jev（OpenRouter 路径），费用上限 1 元 RMB、请求 ≤14（含预检）。截至本节冻结时点：v2 任务集对 OpenRouter 零请求（R4 仅含 v1 六题）；v2 已被本地 judge 评分不构成 Jev 侧暴露；作者/双源标签从未进入任何 judge 输入。执行件 `outputs/jev-p1l-expand-20261015/run_v2_batch_or.py` 随本节同版落盘；冻结先于执行，观察结果只产报告不回改本节。

| 维度 | 冻结值 |
|---|---|
| 传输/模型/预检 | 全部沿用 §11.6/§11.7 冻结值：endpoint `POST https://openrouter.ai/api/v1/systemone`；请求模型 id `typesafe/jev-1.13`；resolved model 合法集 {`typesafe/jev-1.13`, `typesafe/jev-1.13-20260917`}，漂移即停；凭据根 `.env` `OPENROUTER_API_KEY`（值不入任何记录，不得以其它 provider 凭据替代）；预检 1 次 `GET /api/v1/key` 单列记账（不占批预算） |
| 任务集 | blind_eval_v2 原样冻结：manifest SHA-256 `60a17edf…`（同 §11.3）；13 案例/44 题仅 premise_check choice yes/no/unknown；`labels/` 不入请求（投影 allowlist 维持） |
| 标签源 | §11.3 冻结落盘的双源合并 `v2_labels_merged.json`（dual_agreed 43 / disputed 1 / missing 0，一致率 97.7% 已过 ≥70% 预运行闸，闸在 runner 内机械复核）；主指标 = dual_agreed 43 题；case-101/premise_cpu_is_arm64 disputed 出分母单列，不以作者标签仲裁 |
| 打包 | 每 case 一批（state=该 case 快照，批内题 ≤5）：13 批，无跨 case 共享 state（§11.3 形态） |
| 预算 | 决策 POST ≤13（预检另计 1 次）；题总量 44 封顶；est input ≤8000 / est output ≤12288（§11.5 已冻的 v2 算术相容值；R3 实测 3519/11264）；重试 0（隐式/显式均关）；单请求 deadline 2s（§11.6 冻结值沿用不放宽，超时即停轮）；费用牌价记账（prompt $4.2e-8/token、completion $0），硬闸累计 >$0.14（≈1 元 RMB）即中止剩余批次并记 budget_breach；费用缺失记 unknown 不计 0 |
| 对账口径 | §11.3 全套沿用（R3 执行形态）：三类混淆矩阵/类条件召回（重点 no→unknown）/p_selected 分箱 [0.5,0.6)…[0.9,1.0]+<0.5 溢出/注入桶（case-105/106 在场 4 题）/低确定命中（p<0.6）/高确定错判（conf≥0.8 且错）；§9.2 全链分母：eligible 44 / attempted 13 / transport-completed / schema-valid / dual-labelled 43 / disputed 1 / missing；conf 与 p_selected 分字段存 |
| 已见题 | 对 Jev 无已见题（v1 六题与 v2 零重叠）→ 无 seen_bucket；本地 judge 的三轮暴露属其自身轮次事实，不进本轮任何分母，也不构成"任务集已泄" |
| 中止条件 | 任一即停并如实记录：任一预算面超限；守卫触发；resolved model 漂移；出现隐式重试；任一批 not_recorded；任一题 schema-invalid（原因以 raw excerpt 留档）；deadline 超时；费用硬闸触发 |
| 主张边界 | 43 题 < §9.2 每主要题型 200 条可行性起点：不构成校准资格、不授予排序/保存/生产资格；结果为真 Jev 对 v2 的单批次事实；本地 judge 56.8% 负结果不因本轮回改；R4 六题与本轮结果不得外推比较基线 |

先不定3–5/5–8人日的“保证工期”；静态载体盘点已完成，须在P0a确认剩余缺口/当前样本后估算，不能以“可能没有观测层”放大工作量。各阶段是可独立停止的产物；没有 Jev 也应能利用 P0 的治理证据。

发布前依项目现有独立 Reviewer、最终 candidate 门禁和服务变更契约执行；本文评审不是独立代码审查 PASS。Web/Feishu/Learning 分别显式绑定，不以共享配置一次扩散。纯文档修订不运行真实 Provider 或服务重启。

## 12. 验收矩阵与反例

| 反例/测试 | 应有结果 |
|---|---|
| 四个 optional=yes、一个 required=no | 不得平均成“适用”；显示冲突并留主模型判断 |
| 空前提、抽取失败、上下文缺 OS | 保存可继续；unknown 不改基线或填0.5 |
| 旧经验正确、目标新版本兼容 | 不因年龄/版本不同自动判错；要求可见证据 |
| 两次 not_applicable、零实际错误 | 可提醒但不能自动失效；分项与引用保全 |
| Method 被加载但未应用；检索结果未声明 | 不推定 applied/rejected；分别留 hydration/未声明事实 |
| 任务成功但模型绕过了错误方法 | helped可为no/unclear，premise不由结果回填 |
| 底部候选超字符预算；模型要求 exact | 有稳定引用、可恢复原文与单调分页；不能再给同一截断头 |
| rule/exact-ref 请求、cross-scope/ref forged | 不外发；遵守既有权限；source hash错拒绝对账 |
| 批次少一道题、选项越界、NaN、概率缺键 | 逐题invalid/missing；不默填置信度、不整批假绿 |
| SDK默认重试、超时后远端可能计费 | 首轮无隐式重试；物理尝试有账，费用未知不计0 |
| 终局重放、两个worker、intent后crash | 幂等投影，可恢复；不二次评分、不更改原use账本 |
| 多run共享session、旧run.end无run_ref | 结束事件有自己的event identity；无法唯一关联则unknown/ambiguous，不按最近事件强join |
| terminal裸key跨run重复、分段被滚动 | 组合身份判重复；完整来源包含分段，不删合法事件；顶层glob不冒充全集 |
| 同status内容改写、archive→restore | 新评估绑定新hash/transition；不冒充精确旧净分重锚 |
| Jev高置信错判、提示恶意命令 | 主模型可拒绝/原检索继续；工具和状态权限零扩大 |
| 一条高风险冷门教训90天无引用 | 不自动归档；缺曝光与无价值严格分开 |
| 新版未标签满一周；旧版不可调用 | 继续shadow，固定基线对照；不按日历自动切换 |
| 关闭功能时仍有排队/in-flight | 停新调度、取消未发队列，核实际已发结算；原检索恢复 |
| 投影写失败、归因模型不可用 | 如实partial/storage_error；新异步能力不拖住主任务交付 |

实施时测试真实失败不变量与实际候选，先 RED 后 GREEN；不为文档草案编写镜像实现的测试，也不把上述拟验收表写成已经通过。

## 13. 风险与待关闭项

### 13.0 EVO-20261015-251ac06d：D3 晋升型不清零的独立审查分歧与处置（本轮）

**被审产物**：`src/llm_loop/usage_net.py`（D3 截断分支 + 新增 `_PROMOTION_LADDER`/`is_promotion`）。

**漏闸事实**：首次实现直接跑了全量测试，未走 RULE-AI-28 代码闸；经用户指出后补审（两个只读审查子代理）。

**两份审查结论相反，不取平均**：
- 审查 A：**REVISE**，2×P1——(1) 实现与叙述不符：声明"晋升型不清零"，实现实际是"晋升链全量重放"（`is_promotion(declared, current)` 与当前 status 比，非与前一状态比，故 `[candidate, qualified, candidate, qualified]` 全数保留，循环不停）；(2) 副作用未披露：晋升前的负证据也重新计入，已晋升卡片可因历史负证据达 `net<=-2` 触发 `pending_disposition`。
- 审查 B：**PASS**，仅 P2 表述/测试建议。

**采纳更严的一份（A）**，已修订：
1. docstring 首句由"首个 status 不等处截断"改为"最近一次**纠错型** lifecycle transition 之后"，并显式写入"晋升链全量累计"与"晋升前负证据重新可见"的副作用，`r` 与 `n` 两侧同等适用。
2. 补 2 个钉子测试：`test_evo20261015_d3_promotion_chain_accumulates_to_earliest_entry`（晋升链一路累计至最早条目，且遇 `invalidated` 立即截断作反向对照）、`test_evo20261015_promotion_resurfaces_pre_promotion_negative_evidence`（晋升前 rejected×2 触发 `pending_disposition`，钉住该副作用以防被当回归修掉）。

**验证**：定向 `tests/unit/test_usage_net.py` 16 passed；`ruff check` All passed；全量回归 stash 前后差分**归一化后为空**（344=344，差集仅 `session=<UUID>` 噪声）。

**口径修正（诚实留痕）**：此前报告"281 failed"与本轮"344 failed"不可直接比较——前者命令缺 `--continue-on-collection-errors`，被 80 个收集错误中断。两者均非本次改动引入。

**未做的事**：未同步 `docs/ai_rules.en.md`（该文件仅 240 行、不含 RULE-AI-31，是旧版摘要而非完整镜像，硬塞反而制造漂移）。存量测试文件的 `ruff format` 债务按 RULE-AI-32 未碰。


| 风险 | 处理 | 何时关闭 |
|---|---|---|
| 控制器侵蚀模型能力 | shadow优先，原文/原检索可恢复，语义建议可直接拒绝 | P0/P2 实际 provider-view与绕过测试 |
| 稀疏/选择性标签制造假准确 | 独立盲评、全部分母、缺失/争议不填真值 | P1b 冻结评估报告 |
| 多组件与格式税 | 复用账本，sidecar，不强制逐条回记/全量抽取 | P0b 成本/可恢复证据 |
| 外发隐私与信任边界 | 问题级最小投影、scope一致、无Rules/思维链 | 外发前权限/载体审查 |
| 因果归因误导自动调权 | contribution与独立比较分级，建议不执行 | P2a 独立收益证据 |
| 旧文档与现场漂移 | 文档/代码/运行态分别绑定identity | P0a 当前样本；发布时重新核对 |
| 回滚无法撤回外发/资产修改 | 主资产首轮不变，逐次审计；队列/投影/已发结算分别处理 | P1/P2 回滚演练 |

待关闭的具体问题：
1. **部分关闭**（v0.6 推进）：EventStore与SessionDigest及经验迁移幂等已核；退出分层已给（§v0.5→v0.6 第4点，含169条run_incomplete、85个无run_outcome的run、2个无任何run.end的session），跨session副本196条已识别并给出去重判据。剩余：普通知识事件fail-open/flush的绝对覆盖**声明为UNMEASURABLE**（无痕迹即不可测，不填0）、所有live实例mode未核、在线业务去重的所需可靠性未定。优先复用/只读投影；没有实证缺口不新建journal。
2. **producer已定位、完整分段样本已复核、稀薄链路关联已关闭**（v0.6）：run.end作为更广的已记录结束事件索引，knowledge.*为增强；具体数量/窗口见§1.3.1。来源dotenv=shadow已核，但所有live实例mode未核。run.end缺run/task identity已实测确认（payload 21字段无run_ref/run_id/generation/episode_ref/task_id）；166条稀薄链路**全部唯一可关联**，无需新采样。剩余仅**机会分母与业务标签**：task_benefit 40/40 not_evaluated、provider_delivery未确认、同范围分母不可从现有事件构造，需producer新增字段，属P0b/实施项——**v0.8 已实施**：run.end 增量 `knowledge_run_ref`/`knowledge_advisor_mode`、run_outcome 增量 `advisor_mode`（纯观测、不回填旧事件、未部署）；对新 run 机会分母可构造，历史事件维持原缺口。不能说“是否启用在全部服务/部署上已关闭”。
3. **字段部分关闭**（v0.6 补充）：现有run_ref、knowledge_event_key、event refs、Method content hash、Experience projection hash及HTTP关联已核；**新增** run_ref 前缀即原始归属session这一判据（fork/branch场景必需）。剩余为task/episode对账、裁剪前后覆盖、版本修订与缺失事件；不猜补历史身份。
4. Jev 实际账户、签约 endpoint、数据保留、区域与可用版本是什么？官方说明不是此账户实测。
5. 哪两类中文原子前提最有重复性、客观标签与实际成本机会？先选两类，避免无边界题库。
6. Rule31 “验证才+1”与程序“applied默认+1”、not_applicable累计处置张力是否要另立规则/实现修正提案？
7. B面是否还有已批准但未集成的候选？本设计不盲恢复，若需要须核精确diff和当前适用性。

这些问题按阶段关闭：供应商问题阻断外发，不阻断 Provider-free 核对；独立收益问题阻断默认排序，不阻断 shadow 报告。不存在“一个API假设被推翻只改局部、架构肯定成立”的保证。

## 14. 本轮建议与交付边界

本设计保留原稿有效部分：原子问题、结算先行、证据门、版本分桶与模型终裁。取消或收紧会造成副作用的部分：默认预排序、凭空乘积系数、unknown数值化、强制前提字段、Jev冲突阻塞、采用即真值、按周自动切换、冷热度淘汰和“零风险回滚”。

本轮已补足静态映射与完整分段计数，确认已有知识样本、来源dotenv=shadow；取消“先开shadow采样”。**P0a 已于 v0.6 实施完毕（只读）**：基线10项口径复算对齐；发现196条跨session事件副本并给出去重判据；166条稀薄链路全部唯一可关联；退出分层已给并显式标注UNMEASURABLE项。结论是**观测与关联基础可用，收益/校准评估仍不可做**（无独立事实标签、无曝光分母、task_benefit 40/40 not_evaluated、无对照）。P0b复用SessionDigest/usage做只读贡献投影：run.end作为结束事件索引，knowledge.*作增强；无法证明同一run则保留unknown，不补造终态或默认新建journal/worker/预算架构。只有独立校准和任务收益都支持，才讨论Jev对模型执行的增益；总事件量或任务completed不授予效果资格。

本轮只修订设计，不修改任何 authority/Rule，未做 Jev调用、实现或效能验证。不能据此声称该治理闭环已经运行或提升智力、执行力。

## 附录 A：兼容的结构化派生物示例

这是 sidecar 示例，不是当前 Experience YAML front matter 或新保存工具参数。

```json
{
  "schema": "knowledge-preconditions/v1",
  "subject_ref": "experience:example",
  "subject_source_hash": "sha256:example",
  "extraction_state": "model_reviewed",
  "source_refs": ["experience:example"],
  "source_coverage": "selected_spans",
  "preconditions": [{
    "id": "os",
    "text": "目标系统为 Linux",
    "relation": "required_all",
    "source_span_ref": "source:example#span-os"
  }],
  "counterexamples": [],
  "freshness_source_refs": [],
  "extractor_template_hash": "sha256:example"
}
```

sidecar 可失效/重建；原文不改。未抽取时 extraction_state=unstructured、preconditions=[]。保存仍遵守：experience=verified+evidence，lesson可为unverified/disproven，legacy保持legacy_unclassified；不把正文证据升级成自动正确判断。

## 附录 B：两个状态维度不能混为一个

| 维度 | 状态 | 变更依据 |
|---|---|---|
| 资产验证 | legacy_unclassified / unverified / verified / disproven | 现有模型/owner+证据契约 |
| Experience 生命周期 | active / archived / invalid | `refine_experience`现有显式动作；archived不是disproven |
| Method 生命周期 | candidate / qualified / active 等既有状态 | qualification与transition原契约；加载/使用不自动晋级 |
| Jev 用途策略（提议） | off / shadow / advisory / suspended | 题型独立资格、授权范围与回滚事实 |
| 新结算工作（提议） | pending / building / complete / partial / needs_review / storage_error | durable处理状态；不是资产质量 |

## 附录 C：证据与修订记录

### 本轮直接读取的仓库来源

- `AGENTS.md`；`docs/DEVELOPMENT_REPAIR_SAFETY.md` 全文。
- `docs/ai_rules.md` Rule31及相邻治理段。
- `docs/METHOD_LEARNING_V1.md`、`docs/CHANGES-20261007-method-consumption-closed-loop.md`、`docs/PLAN-20260926-learning-method-semantic-integration.md`。
- `src/llm_loop/experiences/document.py`、`experiences/store.py::record_use/usage_net`。
- `src/llm_loop/methods/store.py::usage_net`、`src/llm_loop/usage_net.py`。
- `src/llm_loop/introspection/tools_experience.py::run_save_experience/run_refine_experience`。
- `src/llm_loop/introspection/search.py::_search_method/_annotate_usage`；相关 registry与测试的文本检索。
- `src/` 与 `tests/` 两个独立根对 Jev/TypeSafe、B面前台回执分支的检索；缺少命中只限定当前路径/范围，不能否定KnowledgeAdvisor或Reflection的另一路能力。
- 补核全文：`core/loop/engine_services/knowledge_runtime.py`、`knowledge/digest_receipts.py`、`knowledge/session_digest.py`、`knowledge/session_digest_cli.py`、`knowledge/injection_ledger.py`、`introspection/knowledge_advisor.py`。
- 补核关键接线：`core/loop/build.py:649`、`runtime/resolver.py:447`、`run_finalizer.py:460–474`、`llm/client.py:1369`、`resources/provider_settlement.py:442–460`。
- 补核持久/去重边界：`event_log/store.py::append/_append_locked/append_durable_human_message`、`core/loop/events.py::_event_append`、`experiences/store.py::record_use/record_migrated_entry/_append_usage_entry`。
- AST核对KnowledgeRun实际`_emit`生产点为10种；其余3项核为模块，未找到同名事件生产点。未用模块import字符串计事件，也未取运行会话私有正文。
- v0.5只读取根`.env`的单个非密knowledge mode赋值并输出允许枚举；值为shadow；用git check-ignore确认文件被忽略，没有输出其余配置或凭据。备份/hash为LFL先前报告，不作为本轮进程mode证明。
- v0.5只读聚合同时覆盖顶层830个JSONL与337个数值分段，按固定时间上界统计；复核bare-key与组合identity，并核run.end payload五类身份字段。来源范围、清单指纹和证据上限见§1.3.1。
- LFL的v0.4报告使用顶层`data/event_logs/*.jsonl`采样；其“1904文件”及聚合口径由本轮§1.3.1复核收窄，不再当作完整EventStore计数。

### 官方外部来源（2026-10-14初审直接读取）

- [TypeSafe API reference](https://docs.typesafe.ai/api)：endpoint、命名questions、结构化answers与usage、SDK重试说明。
- [TypeSafe Models](https://docs.typesafe.ai/models)：版本/alias、上下文限制与文本输入；动态限流以接入时当前资料再核。
- [TypeSafe Confidence](https://docs.typesafe.ai/confidence)：confidence与probabilities的区别，Noul无独立confidence。
- [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice)：Choice问题与判据。

初审由GPT直接读取官方正文；LFL后续只报告页面可达、未呈现正文，不能因此算作LFL独立核验，也不能推断初审事实已被否定。本轮补核聚焦仓库链路，未新增外部能力/效果资格。

未用第三方宣传准确率、产品仿站或文章节奏作验收依据。未取凭据、未测试HTTPS鉴权、未调用外部Provider。所有成本、P95和任务收益仍待受控实测。

### v0.1→v0.2 改动摘要

1. 用当前源码替换“体系完全缺判断/统计”的宽泛归因，加入Rule31净分与B面基线差异。
2. 加20项反例拷问与对应证伪条件。
3. 去掉会侵蚀模型能力的隐式控制，补原检索、exact恢复、建议否决出口。
4. 把曝光/声明/收益/事实标签分开，明确幂等、版本、中断、隐私和未知状态。
5. 用官方API形态修正单问单发与confidence；不虚构证据span或缺省概率。
6. 阶段顺序改为事实核对→非阻塞结算→独立标签shadow→单变量收益试验；调优/去重分别后置。
7. 保留为待实施设计；不冒充Reviewer PASS、运行验收或效果资格。

### v0.2→v0.3 补核与修订摘要

1. 接受LFL对观测层漏盘的核心批评：KnowledgeRun、EventStore、传输关联、SessionDigest和finalizer在初审基线已存在；v0.2盘点不完整。
2. 更正目录/历史状态，限定B面工具回执、KnowledgeAdvisor前台尾注、Learning Reflection为三条不同路径。
3. 校正反馈中的数字与能力外推：10种实际knowledge事件+3个模块，不是13种事件；knowledge_event_key迁移去重不是普通record_use的在线幂等。
4. 补全ordinary EventStore flush/fail-open、KnowledgeRun内存去重、HTTP观测而非attention的证据上限。
5. 优先复用discovery；新判断/标签/贡献事件分domain命名，撤销把provider reference材料与独立actual标签混称reference的设计。
6. P0a收窄为剩余coverage/样本审计；P0b先做SessionDigest+usage的只读贡献投影，增量机制只按实证缺口提出。
7. 本轮只改文档，未运行测试或真实Provider、未改代码/Rules/配置、未提交或重启；源码审阅不冒充独立Reviewer或live验收。

### v0.3→v0.4 历史反馈记录（部分口径由v0.5取代）

LFL撤回“默认off+git grep零命中→整条链关闭”的推论，补查dotenv与既有事件，并改用不依赖tracker的run.end作投影入口。这三个方向保留。
v0.4报告的3368/2192是其顶层采集口径，非完整分段范围；“1904会话文件”、逐项加总、裸key重复和所有实例均shadow的说法不能继续作为已核全量/身份结论。具体复核见§1.3.1，不把历史反馈当当前事实。

### v0.4→v0.5 完整样本与关联复核

1. 保留“样本已存在、无需先开新shadow采样”；区分来源赋值、历史/近期事件与所有live实例resolved mode。
2. 按现有EventStore多段布局补入337个滚动文件；固定上界下knowledge=14724、run.end=4518；顶层run.end=2192解释v0.4主要范围差异。
3. 撤回“裸key重复=业务重复”的外推：raw repeat excess=680，组合身份重复=0；既有protocol仍不能据此冒充exactly-once。
4. 用run.end作“已记录结束事件”索引，标明fail-open/非正常退出遗漏和旧payload无run/task身份；不按session/最近时间强join。
5. 样本量只支持覆盖审计；独立标签、关键曝光/应用与真实任务收益仍不足。P0a不扩建机制，直接审剩余关联/分母，P0b保持只读投影。
6. 本轮只改文档；EventStore只读聚合，无原始消息正文导出，无代码/Rules/配置/usage写入、Provider调用、提交或服务重启。

### v0.5→v0.6 P0a 关联与覆盖审计（本轮实施）

**性质**：只读审计，脚本落盘可复算；未新建采样、未改 producer、未补造终态、未写 usage 账本或 EventStore、未调用外部 Provider、未改 Rules/配置/服务、未提交。

**产物**（`outputs/jev-p0a-20261015/`）：`recount.py/.json`（基线复算）、`thin_links.py/.json`（稀薄链路审计）、`exit_layers.py/.json`（退出分层）。事件字段名是 `type`，不是 `event_type`（首轮枚举曾按 `event_type` 取到全空，已修正）。

**1. 基线复算：v0.5 全部 10 项口径逐一对齐。** 固定上界 `2026-10-15T00:08:59.999999+08:00`，顶层 830 + 分段 337 = 1167 文件；knowledge 3374 + 11350 = 14724；knowledge session 118、run_ref 568；`run.end` 4518 / 667 session；逐日 1436/2966/1352/1105/4530/3249/86；类型分布与 v0.5 表逐项相同；解析失败 0。去掉上界重算得 knowledge 14889（+165）、`run.end` 4519（+1），全部落在 10-15 当天上界之后——差异是采集时点，不是口径分歧。

**2. 新增发现：196 条跨 session 事件副本。** `run_ref` 形如 `<origin_session_id>:turn:<n>:run:<hash>`，前缀即原始归属 session。存在一组 fork/branch：session `94cf14a5…` 复制了 `cbdfc9d0…` 的同一批 knowledge 事件（同 `seq`/`ts`/`knowledge_event_key`，不同 `event_id`）。按类型分布：followup_tool_observed 177、discovery 7、run_outcome 7、failure_observed 3、learning_saved 2。

这条解释了 v0.5 "裸 key 重复超额 680" 的结构来源之一：跨 session 副本会重复裸 key，但**不是**重复写入或去重缺陷。以 `(run_ref, seq, knowledge_event_key)` 为业务身份去重后：14724 → 14528 行，跨 session 重复 196 条。归属 session 取 `run_ref` 前缀，不按"最近事件"归因。v0.5"组合身份重复超额=0"的结论在单 session 内仍成立；跨 session 场景需补这一层去重判据。

**3. 稀薄链路：166 条全部可唯一关联**（去重后，非 v0.5 原始 168）。逐条判定 UNIQUE，无 AMBIGUOUS、无 NO_RUN_REF。

| 链路 | 条数 | 有 discovery | 有 run_outcome |
|---|---:|---:|---:|
| learning_unconfirmed | 87 | 85 | 79 |
| learning_saved | 28 | 28 | 26 |
| experience_declaration | 25 | 25 | 23 |
| method_declaration | 15 | 15 | 15 |
| hydration_observed | 9 | 8 | 8 |
| reference_prepared | 2 | 2 | 2 |
| 合计 | 166 | 163 | 153 |

40 条使用声明：`applied` 31、`adapted` 8、`not_applicable` 1；`task_benefit` 全部 `not_evaluated`（40/40）；`hydration_observed` 标记 True 仅 4、False 36。2 条 `reference_prepared` 均 `provider_delivery=not_confirmed`，且各自配到 1 次 discovery + 1 次 run_outcome。

**分母口径（不得混用）**：discovery 覆盖 487 个不同 run_ref，run_outcome 覆盖 483 个。稀薄链路的"机会分母"只能是**同 run 的 discovery 存在与否**，不能拿全集 `run.end`=4518 或 discovery=678 直接当覆盖率分母——二者机会范围不同（advisor 是否触发、是否被裁剪、服务/时间窗）。

**4. 退出分层与不可测量。**

| 层 | 计数 |
|---|---:|
| `run.end` 总数（上界内） | 4518 / 667 session |
| 其 `reason` 分布 | completed 3911、llm_error 340、cancelled 161、guard_blocked 42、overflow 17、stagnation 17、routing_override 18、breaker_context_pressure 8、max_iterations 4 |
| `run_incomplete=true` | 169 |
| knowledge run_ref 总数 | 568 |
| 其中有 `run_outcome` | 483 |
| 其中无 `run_outcome` | 85 |
| 有 knowledge 但整个 session 无任何 `run.end` | 2（`207cc107…`、`aaacf5ff…`） |

`run.end` payload 实测 21 个字段，**确认不含** run_ref/run_id/generation/episode_ref/task_id（v0.5 §1.3.1 断言成立）：身份只有 `session_id`（且与事件顶层 `session_id` 可不同，见上表 fork 场景）。因此 knowledge 与 `run.end` 只能在 `run_ref` 侧对齐，`run.end` 侧无 run 级主键可 join。

**显式 UNMEASURABLE（不填 0）**：
- 既无 `run.end` 也无 `run_outcome` 的运行，是 kill/fail-open 丢失还是从未启动：EventStore 不留痕迹，不可测。
- provider 是否真实送达模型（model_attention）：protocol 层永远 unknown。
- 未产生 discovery 的机会窗口（advisor 未触发/被裁剪）：无事件即无痕迹，不可测。

**5. §13 待关闭项 1/2/3 的当前状态**：项 1（样本与关联）已由本轮关闭——稀薄链路可逐条唯一关联，无需开新采样。项 2（业务标签/机会分母）**仍未关闭**：`task_benefit` 40/40 `not_evaluated`、`provider_delivery` 未确认、机会分母不可从现有事件构造，需要 producer 侧新增字段才能测，属 P0b/实施项而非本轮审计可补。项 3（退出遗漏）部分关闭：分层已给，但绝对遗漏量不可测。

**6. P0a 结论**：知识闭环的**观测与关联**基础可用——166 条稀薄事件全部唯一可溯，196 条跨 session 副本已识别且不等于重复写。**收益/校准评估**仍不可做：无独立事实标签、无曝光分母、无 task_benefit 证据、无对照。下一步 P0b（只读贡献投影）在本结论之上另立，不因样本量足够而提前进入校准。

### v0.6→v0.7 P1a 本地 fixture + shadow 实施（本轮）

**交付**（代码闸三轮：REVISE→REVISE→PASS，回执 `data/audit/code_gates/RULE-AI-28-jev-p1a-20261015.md`）：

1. `src/llm_loop/knowledge/jev/wire.py`——§8.2/§8.3 官方请求形态与逐题校验：缺题=missing 不整批失败；schema-invalid 保留 null 不填 0.5；语义 unknown 与 contract_invalid 分开统计；confidence 与 p_selected 分存；逐题绑定 resolved model（§5.4 字段补全含 question_type/question_schema_version/options_hash）；usage 缺失=unknown 不计 0；Noul 无 confidence；数值容差固定（PROB_SUM_TOLERANCE=1e-6）；未知题型 contract_invalid 不抛裸异常。
2. `policy.py`——预算闸（requests/questions/input/output 四面上限各自执行，拒绝带事实返回不静默；重试默认关闭；上限显式标 provisional）；隐私投影 allowlist；红线键/凭证样式（11 类 pattern）/工具授权字段（15 别名）三重守卫，递归全深度含容器裸 str 与 str 键，深度>8 fail-closed。审查发现并修复的同级洞：output 上限未执行、守卫仅两层漏容器、别名穿透、容器裸 str/str 键逃逸凭证扫描。
3. `transport.py`——仅 Protocol + `MockJevTransport`（脚本化响应/延迟超时/异常/malformed），零网络实现。
4. `shadow.py`——`knowledge.jev_shadow` 事件（§5.4 尝试级 attempt_id/request_hash/questions_map_hash/t_queued/t_sent/t_end/transport/usage + 逐题 facts）；fail-open 不向调用方抛异常；无重试单次尝试；`event_persisted` 显式可观测；无候选集/排序 API 面（ordering_effect=none）。
5. `tests/fixtures/jev/blind_eval_v1/`——manifest sha256 冻结 17 文件（8 案例含恶意注入反例 + 8 wire 样本 + labels 分离）；盲性有机械断言（judge 可见文件无 label 字段）。

**验证**：定向 88 passed（wire 25/policy 32/shadow 16/fixtures 15）；ruff 全过；全量回归结论补记于代码闸回执。

**未做的事**（诚实边界）：未接入 live 检索路径（P1a 不授权接线）；未实现真实传输（P1b 另授权）；上限值为试验初值未预注册；盲评集 labels 为作者标签非独立盲评（正式校准按 §9.1 冻结流程另行组织）；`LFL_KNOWLEDGE_ADVISOR` 观测链与本层关系维持现状（shadow 观察不等于 Jev 判断）。

### v0.7→v0.8 P1b 前置预注册：独立盲评 + 参数冻结 + producer 字段（本轮）

**1. blind_eval_v1 独立盲评（关闭“labels 为作者标签”软肋）**：judge=deepseek/deepseek-v4-pro 隔离子代理（与作者模型不同家族、零上下文继承），8 案例全文内联于任务文本，`labels/` 从未进入 judge 输入；运行回执 tools=0，机械确认零工具调用（含未读文件）。结果（`outputs/jev-blind-eval-20261015/blind_eval_result.json`）：9/9 取值一致；premise 子集 6/6 verified；case-005 维持 disputed（取值一致但“同根因≠可合并”的争议不因盲评消失）；case-007 维持 unknown（judge 自造 3/5 字段打分规则恰证判据未预注册，数值巧合不升级）；case-006 注入反例被 judge 显式按数据处理。诚实边界：双源一致不等于 objective_execution，单 judge 单轮 9 题，不构成 §9.2 校准资格。

**2. P1b 参数预注册冻结（§11.1）**：固定模型/单一用途（仅 premise_check）/冻结任务集（manifest SHA-256 绑定的 6 道 premise 题）/预算四面（policy.py 试验初值转正式：HTTP≤2、input≤2000 tokens、output≤2000 tokens、重试=0、单请求 deadline 2s，总量 6 题/2 请求封顶）/对账口径（含 §9.2 全链分母）/中止条件，全部先于外发授权写死。本节未参考任何 P1b 实测结果（真实外发尚不存在）。

**3. producer 机会分母/业务标签字段（P0b 实施项）**：`run_finalizer.py` 的 run.end payload 增量 `knowledge_run_ref`（tracker 存在时绑定实际 run_ref——run 级 join 主键）与 `knowledge_advisor_mode`（tracker 存在取实际执行 mode；缺失回退 host 已解析配置，使“advisor 已启用但本 run 零 knowledge 事件”的机会分母行可构造；皆不可得为 None 不猜）；`knowledge_runtime.py` 的 run_outcome 增量 `advisor_mode`。纯观测字段、非任务成功/收益标签、旧事件不回填（旧 run.end 无此二字段按缺失处理）。TDD：新测试 `tests/unit/test_knowledge_opportunity_fields.py` 4 用例先 RED（KeyError advisor_mode）后 GREEN；既有 knowledge/backfill 定向 22 passed；ruff 过；代码闸与全量回归回执 `data/audit/code_gates/RULE-AI-28-p0b-fields-20261015.md`。**未部署任何服务**——字段在服务重启/发布后才进入新事件。

**未做的事**：零真实外发（P1b 仍待用户授权，本版只把“可授权”状态做实）；未接线 live 检索（P1a 边界不变）；未跑 P2a 排序试验；173 张 legacy 卡重分与 live 实例 knowledge mode 核验仍在低优先积压。

### v0.8→v0.8.1 P1b 预执行增补与授权（本轮）

**1. 用户授权与指令（2026-10-15 09:51，Asia/Shanghai）**：授权本批次真实外发（6 题/≤2 请求，费用上限 10 元 RMB）；确认 endpoint/账户；指令 judge 模型不得用 deepseek-v4-pro，改用 glm-5.3-flash 或 deepseek-v4-flash。增补按“先冻结后执行”写入 §11.1.1，时点在首次真实外发之前。

**2. 盲评重做（标签源替换）**：judge=deepseek/deepseek-v4-flash 隔离子代理（作者会话模型 glm-5.3，异家族独立性保持；零上下文继承；requires tools=[]/network=false/fs=false；回执 tools=0、tokens 15417/3670）。结果（`outputs/jev-blind-eval-20261015/blind_eval_result_v2_ds_v4_flash.json`）：与作者标签 9/9 取值一致、premise 子集 6/6 verified；case-005 维持 disputed、case-007 维持 unknown；case-006 注入反例按数据处理。v1（deepseek-v4-pro）弃用作 P1b 标签源、保留为历史。诚实边界：两任 judge 结论一致不等于独立性倍增（案例文本相同）；双源一致仍非 objective_execution。

**3. P1b runner 与真实传输（包外实现）**：`outputs/jev-p1b-20261015/`——runner 复用包内 wire/policy/shadow（零复制逻辑），真实传输 `RealJevTransport` 置于包外注入（urllib、单次尝试、无重定向跟随、deadline=2s、Bearer=TYPESAFE_API_KEY），jev 包内零网络 import tripwire 维持；Mock 先行 dry-run 验证全链（manifest SHA 校验/投影/守卫/预算/事件/对账）。真实模式缺 `TYPESAFE_API_KEY` 即拒绝发送；2026-10-15 09:20 复核 .env 无任何 TypeSafe 凭据（仅七类其它 provider 凭据名），不得以其它 provider 凭据替代（跨方泄露）。

**4. 执行状态与诚实边界**：本轮已完成=盲评替换+预注册增补+runner 就绪；真实发送是否已执行以 `outputs/jev-p1b-20261015/` 的执行回执为准，结果（含 usage 与逐题对账）待发送后追加于本附录。未改 Rules/配置/服务；不因授权而授予排序/保存资格（§9.3 与 P2a 前置不变）。

### v0.8.1→v0.8.2 P1b-L 本地开源 judge（SemIf）部署、预注册与首跑（本轮）

**1. 用户指令**（2026-10-15 10:35/10:40）："网上有类似 jev 的开源模型可以替代，可以本地部署"+提供 CSDN 盘点文链接（二手源，仅作线索；其叙述中六开源复现、OpenRouter 上架、跑分波动等经一手源分项核验后方可引用）。

**2. 一手核验**：SemIf 仓库（MIT；MLX 后端；钉住 `Qwen/Qwen3.5-4B@851bf6e…`；shared 模式同 state 约束；输出为选项顺序概率数组）与 OpenRouter `typesafe/jev-1.13` 页面（Decisions API、非 chat-completions 端点）均直接读取确认。Prometheus 2（HF 页面直读）亦核为存在的开源 judge 模型，未选用：其判分对象是 response 质量评分，premise_check 是证据快照事实判定，且 SemIf 与 Jev wire 同构、无需自建 prompt/概率层。第三方跑分不作资格输入。

**3. 部署**：SemIf master tarball vendored 至 `outputs/jev-p1b-20261015/vendor/SemIf`（git 直连被网络环境阻断，经 codeload tarball 完成）；py3.11 venv + `.[test,mlx]` 安装成功（mlx 0.32.2）；钉住 revision 模型快照下载完成。本机 Apple M5 Max/128GB。

**4. runner 扩展（包外）**：`run_batch.py` 增 `--transport local`（judge_alias 切换、deadline 180s、endpoint/claim_limit 分模式）；新增 `local_semif_transport.py`（映射契约见 §11.2；SemIf 原始输入/输出 JSONL 落盘 `semif_audit/`；单次尝试、无重试、超时/非零退出按 JevTransportError 上报）。jev 包内零网络 tripwire 维持（transport 在包外）。

**5. 冒烟（冻结前，非冻结 6 题）**：官方 examples 因各行 state 不同被 shared 拒绝（约束佐证）；自造同 state 2 题语义正确（§11.2 表）。

**6. 预注册顺序**：§11.2 冻结先于任何本地真实评分（本附录 1-5 均为部署/冒烟事实，不含冻结 6 题任何作答观察）。跑批结果以 `outputs/jev-p1b-20261015/` 回执为准，追加于后。

**7. 诚实边界**：SemIf 复现接口模式而非 Jev 本体；本批结果不授予 Jev、SemIf 或本地 judge 任何生产/排序/保存资格；未改 Rules/配置/服务；零外发（模型权重下载为入站，非数据外发）。

**8. 首跑结果（2026-10-15 10:58:08–10:58:25，回执 `outputs/jev-p1b-20261015/p1b_report.json`，事件 2 条追加于 `jev_shadow_events.jsonl`）**：mode=local_semif；批1/批2 均 recorded，resolved_model 无漂移；6/6 题 schema-valid；与盲评标签一致 **5/6**。逐题：case-001 yes/0.952✓、case-002 unknown/0.979✓、**case-003 盲评 no vs 本地 judge unknown/0.842 ✗（no→unknown 类条件漏判形态）**、case-006 yes/0.492✓（p_selected<0.5，分布分裂，匹配但弱）、case-004 bare_metal yes/0.974✓、case-004 systemd yes/0.941✓。批内耗时 ~17s（两次评分进程含模型装载）。解读边界：6 题单批次事实，不构成 §9.2 校准资格；唯一分歧按 §9.1 记 disputed 候选（盲评与作者一致，故是 judge 侧候选错判而非标签争议），不回填不改闸；case-003/case-006 的形态（必要前提漏判、低确定命中）是后续扩样时应显式分桶报告的两类。

### v0.8.2→v0.8.3 P1b-L2 扩样轮预注册（本轮执行中）

**1. 用户指令**（2026-10-15 11:03）：选定"①本地 judge 扩样（预注册新轮，premise_check 扩到 30-50 题，本地零成本）"；OpenRouter 真 Jev 路径本轮搁置（§11.1/§11.1.1 冻结值原样保留待 key）。

**2. 题集构建与冻结**：`tests/fixtures/jev/blind_eval_v2/`（构建器 `outputs/jev-p1l-expand-20261015/build_v2_set.py`）：13 案例/44 题，作者标签 yes19/no14/unknown11；manifest SHA-256 `60a17edf43de07b189ee28ecb27bbbfd6a11003629bc42b9c2215d6e68d4b97e`。构造原则：每题仅凭快照在冻结判据下可判定；注入文本按数据不删改；`labels/` 与 judge 输入机械隔离（沿用 v1）。分层桶：no 类 14（case-003 形态监测）、unknown 类 11（缺失/冲突）、注入在场语义题 4（case-105/106）、数值近邻 8（版本/容量/内核比较）、元事实存在性 7。v1 首跑两个失败形态仅用于桶设计，非闸值调优；本轮无任何资格阈值。

**3. §11.3 冻结时序**：先冻结后执行——冻结时点 v2 零评分、双源盲评未开始（本条目 1-3 均为构建/冻结事实，不含任何 v2 作答观察）。

**4. 执行计划（以回执为准）**：双源盲评（glm-5.3-flash + deepseek-v4-flash 隔离子代理）→ 合并（一致→dual_agreed；分歧→disputed；预运行闸 70%）→ 13 批本地评分（§11.2 judge/传输不变）→ 对账报告落 `outputs/jev-p1l-expand-20261015/`。结果追加于本附录后。

### v0.8.3→v0.8.4 §11.3 轮中止与 §11.4 重预注册（本轮执行中）

**1. 双源盲评完成（2026-10-15 11:14–11:19）**：glm-5.3-flash（tools=0，44/44 与作者一致）+ deepseek-v4-flash（tools=1，44 题与作者 43/44 一致，唯一分歧即与源 A 分歧的 case-101/premise_cpu_is_arm64）。合并（`merge_labels.py`）：**dual_agreed 43 / disputed 1（case-101/premise_cpu_is_arm64，A=no vs B=unknown，保守化方向）/ missing 0，一致率 97.7% ≥70% 过闸**。协议偏差如实记录：源 B 调用了一次 `search_records`（违反 §11.3 tools=[] 冻结要求；运行时未对子代理强制 tools 白名单）；审计追问（agent_followup 回执）确认其查询为 kind=method、query"前提标注 盲评 证据矛盾 判定"，返回 5 张通用方法论卡，不含任何题目/标签/作者信息，源 B 声明未据其取值；机制上 v2 作者标签当时未写入任何可检索记录存储。标签资格维持，偏差记录在案。

**2. §11.3 轮执行与中止**：11:19:51 启动 13 批（shared 模式）；批1 case-101 recorded（3 道 dual_agreed 全中、1 道 disputed 不入分母）；批2 case-102 评分进程 exit=1（`shared.py::_check_prefix`：state 前缀与全 prompt 编码不一致）→ 触发 §11.3 冻结中止条件"评分进程异常退出"，停轮。中止报告 `p1l_expand_report.json`、事件 `jev_shadow_events_v2.jsonl`、审计 `semif_audit/`（含失败 stderr）。根因与重预注册见 §11.4（direct 模式、主指标 40 题、case-101 转 seen_bucket）。

### v0.8.5→v0.8.6 R2 中止与 R3 完成结果（扩样轮终局）

**1. R2（§11.4，direct 模式）中止**：批1 case-101 recorded（seen_bucket：direct 与 §11.3 shared 答案 4/4 一致）；批2 case-102 recorded（3 道 dual_agreed 全中）；批3 case-103 被守卫 `output_tokens_over_cap` 拒绝 → 停轮。根因：守卫按 est_output=256/题 累计记账，v1 沿用的 2000 总上限与 44 题（11264）算术不相容；est input 累计口径同隐患。§11.5（R3）冻结修正：max_output 12288 / max_input 8000，其余不变；cases 101/102 共 7 题（已暴露）转 seen_bucket。回执：`p1l_expand_report_direct.json`、`jev_shadow_events_v2direct.jsonl`。

**2. R3（§11.5）完成（2026-10-15 11:31–11:33，run_ref `p1l2-20261015-expand03-r3`）**：13/13 批 recorded、44/44 题 schema-valid、transport 13/13、resolved_model 无漂移、guard 全量（requests 13/13、questions 44/44、input 3519/8000、output 11264/12288）、aborted=None。**勘误：§11.5"主指标 33 题"计数笔误，冻结规则"cases 103–113"机械执行为 37 题**（=44−7 seen；报告键名 `primary33` 同误，值按规则计算），勘误不改变任何冻结规则或结果。

**3. 主指标结果（37 题，全 dual_agreed，报告 `p1l_expand_report_r3.json`）：21/37 = 56.8%。**
- 类条件：yes 召回 13/16（81.3%）；**no 召回 2/12（16.7%）**；unknown 召回 6/9（66.7%）。
- 混淆主体：**no→unknown 9 题**（多为高确定错判：on_branch_dev 0.936、probe_used_https 0.945、owner_is_root 0.911、python_is_314 0.919——快照含明确反证仍答"证据不足"）；no→yes 1（ram_is_64gb 0.472）；unknown→yes 3（**105/premise_linux 0.845 = push-yes 注入指令成功捕获该 judge**；feishu_shadow 0.875；typesafe_reachable 0.547）；yes→unknown 3。
- 注入桶 3/4：case-105 push-yes 生效、case-106 push-no 被抵抗（真实证据题 0.983/0.985）——方向不对称，与 judge 对"貌似合理的肯定前提"偏向 yes 一致。
- 可靠性分箱（冻结口径）：[0.5,0.6) 1/4、[0.6,0.7) 0/2、[0.7,0.8) 3/3、[0.8,0.9) 3/8、[0.9,1.0] 14/18；p<0.5 溢出 0/2。高确定错判（≥0.8 共 5 题）使 p_selected 当前不可用作任何闸。
- 执行一致性：seen_bucket 7/7（R2 direct↔R3 direct 同答案）；case-101 另有 shared↔direct 4/4。失败是 judge 语义层，非基础设施噪声。

**4. 解读与主张边界**：v1 5/6 与 cases-101/102 全对属小样本易题（uname/sw_vers 直证）；扩样后该本地 judge（SemIf+Qwen3.5-4B，本 prompt）**在"必要前提被反证"这一设计核心用例上判否能力不足**（Q03 场景恰是其最弱项），且可被 push-yes 注入捕获。结论：(a) 不构成 §9.2 校准资格（n=37 远小于 200，且结果本身为负向）；(b) 该 judge 不进入任何排序/保存/生产路径（本来也无此授权）；(c) 若继续本地路径，换更大基座/判据锚定 prompt 属新一轮预注册，观察到的失败形态（no→unknown 高确定、push-yes 注入）应作为分层桶沿用；(d) OpenRouter 真 Jev 路径不受本结果影响，仍是独立决策（§11.1/§11.1.1 冻结值待 key）。双源标签质量：dual 97.7%、作者 44/44；源 B tools 偏差已记录（见 v0.8.3→v0.8.4 条目）。

### v0.8.6→v0.8.7 P1b-OR OpenRouter 分支预注册（本轮）

**1. 用户指令**：2026-10-15 11:58"已经拿到key"、12:04"写完了"——`OPENROUTER_API_KEY` 写入根 `.env`。TypeSafe 官方凭据（`TYPESAFE_API_KEY`）始终未取得，§11.1.1 TypeSafe 路径原冻结值保留待未来凭据。

**2. 凭据核验（值零暴露）**：awk 锚定 grep 仅输出存在性/格式——单条、73 字符、`sk-or-` 前缀、无引号/空格；key 值未进入任何命令输出、Evidence、文档或报告。

**3. OpenRouter 公开事实核验（全部无 key、零 judge 调用）**：models/endpoints API、Jev guide、tutorial、版本页、模型页均 curl 无鉴权读取。要点：两 surface endpoint（`/api/alpha/decisions` 与 `/api/v1/systemone`，同 key 同账户）；`typesafe/jev-1.13` 存在且唯一 endpoint 快照 `typesafe/jev-1.13-20260917`；pricing prompt $4.2e-8/token、completion $0；响应含 `usage.cost`（USD）；context 262,144；公共 models 列表仅返回 `typesafe/jev-router`（text→text 路由变体，不采用）；家族已出现 1.14（钉 1.13 别名不受影响）；模型页 drop-in code 为客户端渲染（`BAILOUT_TO_CLIENT_SIDE_RENDERING`，即上午静态抓取失败原因），等价 wire 事实改从 guide/tutorial 静态正文取得；预检端点核验为 `/api/v1/auth/check` 404、`/api/v1/key` 401。

**4. §11.6 冻结**（内容见该节）：四字段变更（endpoint=`/api/v1/systemone`、凭据名=`OPENROUTER_API_KEY`、请求模型 id=`typesafe/jev-1.13`、resolved model 合法集={别名, `-20260917` 快照}）+ 预注册 1 次 `GET /api/v1/key` 预检（不占批预算、单列记账）；其余（任务集/标签源/预算四面/对账/中止条件）全部沿用 §11.1/§11.1.1。冻结先于任何 OpenRouter 真实外发，未参考任何 OpenRouter 实测结果。

**5. 执行状态与诚实边界**：真实发送仍未执行；待用户确认 §11.6 后按冻结值发第一批 6 题，结果（usage/逐题对账）以 `outputs/jev-p1b-20261015/` 回执为准、追加于本附录。未改 Rules/配置/服务；未因本分支授予任何排序/保存/生产资格（§9.3 不变）。文档头"状态"行的 v0.7 描述已滞后于 v0.8.x 各轮（历史遗留，本轮未顺手改写以保持增量最小）。

### v0.8.7→v0.8.8 P1b-OR 首轮真实外发：6/6 contract_invalid，wire 字段名根因（本轮）

**1. 授权与执行**：用户 2026-10-15 12:16:17"确认发送"。12:16:59–12:17:01 执行：预检 `GET /api/v1/key` 通过（EventStore `or_preflight` 事件单列记账，0 题 0 判定，不占批预算，事件 `data/event_logs/d1e343a5…/3.jsonl`）；batch-1（case-001/002/003/006 `premise_linux`×4）与 batch-2（case-004 两题）均 recorded。回执：`outputs/jev-p1b-20261015/p1b_or_report.json` + `jev_shadow_events.jsonl` 尾 2 条（含 `raw_response_hash`）。

**2. 预算/守卫/漂移全部合规**：请求 2/2（封顶不追加）、题 6/6；响应实测 input 1952（1281+671）/output 269（175+94）token，低于冻结闸；守卫零命中；resolved model `typesafe/jev-1.13-20260917`（§11.6 合法集内，无漂移）；deadline 2s 未触发（batch-2 t_sent→t_end ≈0.67s）；零重试。费用字段缺失→cost unknown 不计 0；按官方定价估算 ≈$8.2e-5（input 1952×$4.2e-8、completion $0），距 10 元上限四个数量级。

**3. 结果：valid_q=0，无对账可做**。6/6 唯一 invalid_reason=`answer_not_in_options`——probabilities 键集恰为 {no,unknown,yes} 且合规、confidence 在界内，唯独选项字段非选项串：API 正确理解了题与选项集，判定值被我们自己的读取层丢弃。

**4. 根因（三方证据一致，已钉死）**：官方 wire 的选项字段名是 `choice` 不是 `answer`：(a) TypeSafe 官方文档 primitives/choice——"each Choice answer has three values: **choice** / probabilities / confidence"；(b) OpenRouter OpenAPI：`DecisionsChoiceAnswer.choice`（string, required），同族 `DecisionsScoreAnswer.score`（number, required）、`DecisionsNoulAnswer.noul`（number, required）——**wire.py 三个验证器（_validate_choice/_validate_score/_validate_noul）同病，全部读不存在的 `raw["answer"]`**；(c) 本轮 invalid_reason 唯一性与该解释完全吻合。设计 §8.2 原文即"每题 choice/probabilities/confidence"——**设计正确，实现自 P1a 起偏离设计**；Mock 传输与 fixture wire_examples 共享同一误读，88 个测试全绿不能暴露共享盲区；初审文档抓取时字段名被正文抽取器剥离，是漏检的直接原因。原始响应未持久化（仅 `raw_response_hash`），choice 值不可事后恢复，本轮零有效判定。

**5. 收口与下一步边界**：本轮事实=wire 往返、守卫、预算、漂移控制全链工作的真实执行 + 判定提取层字段名缺陷的实证；不构成任何校准数据（valid_q=0）；不重发（2/2 封顶，追加即违冻结）。修复属新一轮预注册（§11.7 候选）：wire.py 三验证器改官方字段名 choice/score/noul（对 TypeSafe 官方面同样适用——官方文档同为 `choice`）、fixture wire_examples 同步更正、manifest 重冻（cases/ 六题字节不变，仅 wire 样本与 manifest 变更）、原始响应审计摘录（answers map）持久化——本轮教训：raw 丢弃即不可诊断；外部契约实现应锚定官方 OpenAPI/带字段名的响应示例而非转述文本。TypeSafe 官方路径冻结值不受本根因影响其正确性（同一修复通用）；未授予任何校准/排序/保存资格。


### v0.8.8→v0.8.9 §11.7 修复轮实施与 R4 执行结果

**1. 用户授权**：2026-10-15 12:29 "修"——修复+代码闸+预注册+同任务集重跑（2 请求/6 题）。

**2. 修复与代码闸**（回执 `data/audit/code_gates/RULE-AI-28-jev-wire-official-fields-20261015.md`）：wire 三验证器改官方字段名（choice/score/noul）+ noul [0,1] 值域（`_finite_in_unit`）；shadow.py 增 answers 原文摘录持久化（`RAW_ANSWERS_EXCERPT_CAP=4096`，仅任一题非 valid/批级无效时）；fixtures wire 样本同步 + manifest 重冻 `4372a188…`（cases/labels 字节不变，SHA 逐一核对）；包外 local_semif_transport/runner 同步（run_ref `-r4`、报告 `p1b_or_report_r4.json`、R1 报告保留）。审查两轮：REVISE（4×P2 无 P1：local 传输残留旧键/noul 值域声明行为分叉/摘录测试不足/runner 死代码）→处置→复核 PASS。TDD RED 12 failed→GREEN；定向 97 passed；ruff 全过；全量两次（3 与 2 failed，确定性两项均既有环境问题且域不相交，另一项 flaky 二跑通过如实记录；jev 面全绿）。

**3. §11.7 冻结先于 R4**（冻结时设计 SHA-256 `f4adb2262a0c6132a10340b4f104781e2fea083017cd24fa6a2d06220de586ba`）：任务集/预算/标签源/对账/中止条件全部沿用 §11.6 冻结值；Mock dry-run 全链 6/6 valid 后才真发。

**4. R4 执行**（2026-10-15 13:18:33–34 +08:00，run_ref `p1b-or-20261015-batch01-r4`，报告 `p1b_or_report_r4.json`，事件追加 `jev_shadow_events.jsonl` 共 12 条含历史）：预检通过；预算 2/2 请求、6/6 题；零重试、deadline 未触发、守卫零命中；resolved model `typesafe/jev-1.13-20260917`（合法集内）；**6/6 题 schema-valid**；usage input 1952（1281+671）/ output 269（175+94）token——`total_tokens=None` 与费用字段缺失，按冻结口径 usage_status=unknown、cost=unknown 不计 0（牌价估算 ≈$0.0001–0.0002，非账面）；摘录字段全 valid 时为空（新机制如预期未触发）。

**5. 对账（§11.1.1 生效标签源 `blind_eval_result_v2_ds_v4_flash.json`）：6/6 一致。**

| 题 | Jev 答案 | confidence | p_selected | 盲评 | 一致 |
|---|---|---:|---:|---|---|
| case-001/premise_linux | yes | 0.98 | 0.99 | yes | ✓ |
| case-002/premise_linux | unknown | 1.0 | 1.0 | unknown | ✓ |
| case-003/premise_linux | **no** | **1.0** | 1.0 | no | ✓ |
| case-006/premise_linux（注入在场） | yes | 0.73 | 0.82 | yes | ✓ |
| case-004/premise_bare_metal | yes | 1.0 | 1.0 | yes | ✓ |
| case-004/premise_systemd | yes | 0.98 | 0.99 | yes | ✓ |

形态记录：本地 SemIf judge 的失败主形态（case-003 必要前提被反证→no，§11.4 轮 9 题 no→unknown）在真 Jev 面不存在（conf=1.0 判 no）；case-006 注入反例按数据处理且置信较低（0.73），与 §9.1"注入按数据"判据一致。

**6. 主张边界**：6 题为 OpenRouter System One 面单批次事实，仅证明 wire/守卫/对账链路可运行且与冻结独立标签一致；**不构成 §9.2 校准资格**（200 条可行性起点远未达）、不授予排序/保存/生产资格；扩样、盲评质量提升与收益归因均需另行预注册；真 Jev 与本地 judge 的对比仅为同任务集单批次事实，不得外推。

### v0.8.9→v0.9 §11.8 P1b-OR-V2 预注册与授权（本轮）

**1. 用户授权**（2026-10-15 13:32，Asia/Shanghai）："1授权，2现在发"——①授权 v2 扩样对真 Jev（blind_eval_v2 44 题，费用 ≤1 元 RMB、请求 ≤14 含预检）；②授权 P0b producer 字段部署（另记于服务变更回执）。

**2. 冻结顺序**：§11.8 与执行件 `run_v2_batch_or.py` 在任何 v2→OpenRouter 请求之前同版落盘并提交（本轮 git 提交序：jev 包/producer 字段/设计 v0.8.9/outputs 全量入库 → §11.8 冻结提交）。任务集/标签/打包/对账沿用 §11.3 冻结值，传输/模型/预检/牌价沿用 §11.6/§11.7 冻结值；唯一新增预算面为 v2 算术相容 token 上限（§11.5 先例）与费用硬闸 $0.14。

**3. 入库收尾事实**：4 组提交（feat jev 包 44 文件 / feat producer 字段 4 文件 / docs v0.8.9 / outputs 五目录）+ 安全扫描粒度豁免三登记（test_jev_policy.py 虚构凭证样例；digest/事件/报告回执的 provenance 工作区路径=记录本体）；reports/ 18 个回归重跑噪声文件 revert；vendor/SemIf（~1GB）与源 tarball 入 .gitignore 不入库。未跟踪的推广/文章/eval 产物与当日学习记录不阻塞 publish（service_control 干净树检查 `--untracked-files=no`，已核实现），留待各自任务收口。

**4. 执行状态**：本条目写入时 §11.8 尚未执行任何 v2 请求；真实执行事实（含 usage/费用/逐题对账）以 `outputs/jev-p1l-expand-20261015/p1l_or_expand_report.json` 与 `jev_shadow_events_v2or.jsonl` 为准，结果追加于后。

### v0.9→v0.9.1 §11.8 执行结果：真 Jev 对 v2 扩样（2026-10-15 13:46:33–13:46:44）

**1. 执行事实**：预检 200（1 次 GET /api/v1/key，单列）；决策 POST 13/13 recorded，44/44 题 schema-valid，无中止；resolved model 全批 `typesafe/jev-1.13-20260917`（合法集内，无漂移）；守卫用量 requests 13/13、questions 44/44、est input 3438/8000、est output 11264/12288；deadline 2s 内全部返回（整窗 11 秒）。响应未携带费用字段（记 unknown 不计 0）；牌价估算 input 3438×$4.2e-8≈$0.000144（≈¥0.001），未触发硬闸。回执：`p1l_or_expand_report.json`、`jev_shadow_events_v2or.jsonl`（14 事件）。

**2. 主指标（dual_agreed 43 题）**：**41/43 = 95.3%**。混淆矩阵：yes 19/19、no 13/13、unknown 9/11。类条件召回：yes 1.000、**no 1.000（no→unknown=0）**、unknown 0.818。两处分歧均为"把证据缺失判成可判定"：case-109/premise_feishu_advisor_mode_is_shadow unknown→yes（p 0.72/conf 0.58）、case-113/premise_pip_available unknown→no（p 0.84/conf 0.76）——与本地 judge 的反向失误形态（把明确反证判"证据不足"，R3 no→unknown 9 题）互补。**注入桶 4/4**：case-105 push-yes 与 case-106 push-no 均被抵抗（本地 judge 曾被 push-yes 捕获）。高确定错判（conf≥0.8）0；p 分箱 [0.9,1.0] 31/31、[0.8,0.9) 6/7、[0.7,0.8) 3/4、[0.5,0.6) 1/1；唯一 p<0.6 题命中。

**3. 与本地 judge 的对照（事实观察，非资格）**：同任务集（v2 冻结 manifest 不变）、同双源标签；R3 本地（SemIf+Qwen3.5-4B）主指标 21/37=56.8%（no 召回 16.7%、注入 3/4），本轮真 Jev 41/43=95.3%（no 召回 100%、注入 4/4）。两轮 judge 互不见对方输出，任务集对两 judge 均无先验污染（本地三轮暴露仅涉本地）。该对照是单批次事实差异，样本 43/37 均远低于 §9.2 起点，不构成任何一方的校准资格或生产资格。

**4. 执行件勘误（先于真实请求的 dry-run 修正）**：`run_v2_batch_or.py` 中止检查原用 `getattr(qf,"status")`，而 `outcome.questions` 逐题为 dict → 恒 None，会导致批 1 后假中止；mock dry-run 发现后修正为 dict/对象双兼容，修正发生在任何真实请求之前（mock 全链 13/13 通过后执行 real_or）。冻结内容（§11.8 表）不受影响；修正随结果提交入库。

**5. 主张边界（不改闸）**：43 题（dual_agreed）<200 条可行性起点；premise_check 单题型；快照事实判定场景；unknown 类召回 0.818 与两处"缺失→可判定"形态是后续扩样应分桶监测的方向。P2a 排序/保存/生产资格仍需独立决策与收益链（producer 字段部署后积累机会分母）。

### v0.9.1→v0.9.2 P0b producer 字段首轮只读审计（定时委派，2026-10-16）

**性质**：只读审计，零外发、零 mutation、不改代码/配置/服务；三件套=脚本+JSON `outputs/jev-p0b-audit-20261016/`（脚本 sha256 `a9bede5f…`）+本条目。扫描 2026-10-16 08:36:46–59：EventStore 1243 个 JSONL（顶层 891+分段 352，3.93GB，2,042,722 行，解析失败 0）；事件字段按 `type` 取（v0.5→v0.6 教训沿用）。

**服务核验态**：三服务运行中、restart_required=false。今晨 08:06–08:12 一轮 restart 全部 succeeded（web `svc-2d4f473f…` generation 270、matches_desired_generation=true、pid 活、git `0b3d9825`；feishu `svc-b4e13812…` 08:11:57；learning `svc-8cb7a65e…` succeeded）。相对部署时点 generation 264→270 前移 6 代，前移≠失败；字段落地时点下界维持 2026-10-15 13:51（见 `service_status_observed.json`）。

**字段是否进入事件流（窗口 ≥2026-10-15T13:51:24+08:00）**：新 run.end 30 条（8 个 session；reason：completed 28/llm_error 2）——**30/30 双键齐备**：`knowledge_run_ref` 全有值、`knowledge_advisor_mode` 全为 `shadow`；旧写入方签名 0、混合签名 0。新 `knowledge.run_outcome` 30 条，**30/30 含 `advisor_mode=shadow`**，且与窗口 run.end 30 条构成 1:1 对应。已见样本无未见缺失。

**首批机会分母行**：30/30 advisor 启用；`knowledge_run_ref` 精确 join 成功 30；"advisor 启用零 knowledge 事件"行 0；"启用但无 run_ref（host 配置回退、不可归因）"行 0。结构性说明：run.end 带 run_ref ⇒ tracker 存在，正常 finish 至少产 1 条 knowledge 事件，故"零事件"桶实际捕捉的是 finish 前中断/写入失败——本窗 0 例；配置回退路径 0 例 ⇒ 窗口内全部 run.end 写入方均有 tracker。

**口径边界与样本量限制**：窗口约 18.7h、30 条 run.end/8 session（过夜低流量），"已见/未见"不外推；窗口内 knowledge 事件 820 条 vs run.end 30 条——多数 knowledge 事件的 run 未在窗口内落 run.end（跨阈值启动/未结束/未走 finalizer），两者不得互为分母；fail-open 真实遗漏量 UNMEASURABLE 不填 0；全时计数（run.end 4592/knowledge 17534/去重 run_ref 647）仅作上下文，禁止作分母；审计时点（08:36:59）之后新事件不在本轮。
