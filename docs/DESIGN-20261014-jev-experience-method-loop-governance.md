# DESIGN 2026-10-14：Jev 参与经验/方法闭环治理

| 项 | 值 |
|---|---|
| 状态 | draft v0.6：P0a 关联/覆盖审计已实施（只读，脚本可复算）；尚未获得生产效果资格 |
| 初审/最新复核 | 2026-10-14 / 2026-10-15（Asia/Shanghai） |
| 本轮输入 v0.4 SHA-256 | `47606b0e3f3a6f58ceaa6ff891726a82d57f1a803e2732389e898e77146063bb`；保留其已核方向，仅修订口径 |
| 初次审查基线 | main `5badfc95aadfc286f9c2d8b323cf5932e285c725`；v0.1 当时未跟踪（历史事实） |
| 补充核对基线 | HEAD `2ad0bc06d55aefa3496bdf8c26bad1a4dc2963b2`；初审基线为其祖先 |
| v0.2 入库事实 | `df24e01df5bf3057b9a2586f8e42616f80c0f1f8`（2026-10-14 17:20:40 +0800）；补核前该文件工作树干净 |
| v0.2 SHA-256 | `0443e8540d5337ede81629bfbb33cc7b3cb88b26ce28b6afa1c08bb2314553f5`；v0.3 是本轮文档修订，未在本轮提交 |
| 原稿 SHA-256 | `dcf2200bf8add2b9640390a58b80f1885eba72c13665b9f191b47eb3185a2df0` |
| 定位 | 先补知识消费的证据与对账，再验证可选外部判断能力；模型保留语义终裁 |
| 关联 | `METHOD_LEARNING_V1.md`、`CHANGES-20261007-method-consumption-closed-loop.md`、`PLAN-20260926-learning-method-semantic-integration.md`、`ai_rules.md` Rule 18/22/29/31、`DEVELOPMENT_REPAIR_SAFETY.md` |
| 本次变更范围 | 仅修订本设计；没有改运行代码、Rules、配置、资产生命周期或生产服务 |

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
| P1a 本地 fixture + shadow 方案 | 官方 wire/mock、逐题 invalid、预算/隐私/故障测试、冻结盲评集 | 零真实外发；OFF/shadow 的检索输出一致；完整 negative cases | 维持 OFF；未授权不能启动真实模型 |
| P1b 有界外部 shadow（另授权） | 固定模型/用途/scope/任务集；独立 actual 标签、成本与对账报告 | 不改排序/保存；按类质量与未知比例可审计；API可用≠效果通过 | 超预算、泄露、版本漂移、隐式重试即停 |
| P2a 单变量排序试验（另决策） | 冻结策略、基线组、有限曝光审计、模型绕过出口 | 成功率不退化；返工或全任务成本有可重复改善；关键候选恢复验证 | 恢复原顺序/停调度，不删资产 |
| P2b 去重/分类与建议队列 | 各用途独立 shadow/收益资格、带版本复审建议 | 无静默合并/删除/状态变化；原/新版本证据保全 | 停该用途并隔离派生结果 |

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
2. **producer已定位、完整分段样本已复核、稀薄链路关联已关闭**（v0.6）：run.end作为更广的已记录结束事件索引，knowledge.*为增强；具体数量/窗口见§1.3.1。来源dotenv=shadow已核，但所有live实例mode未核。run.end缺run/task identity已实测确认（payload 21字段无run_ref/run_id/generation/episode_ref/task_id）；166条稀薄链路**全部唯一可关联**，无需新采样。剩余仅**机会分母与业务标签**：task_benefit 40/40 not_evaluated、provider_delivery未确认、同范围分母不可从现有事件构造，需producer新增字段，属P0b/实施项。不能说“是否启用在全部服务/部署上已关闭”。
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
