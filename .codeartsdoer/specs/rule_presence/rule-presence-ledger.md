# 规则在场性台账（rule-presence-ledger）

> **特性**：`rule_presence`（规则在场性）｜**形态**：只读盘点产物（operator surface，离线·fail-open·**非 CI 硬门**）
> **上位依据**：`spec.md`（AC-1~AC-17）、`design.md`（§2.3 数据模型、I6 接口）、`docs/SPEC-20260922-run-convergence-antidrift-v1.md`
> **产出方式**：`scripts/rule_presence_audit.py`（M1~M4）+ 人工四态裁定；本文档**不写**凭证、密钥或私有绝对路径。

## 0. InventoryReport 版本锚

| 字段 | 值 |
|---|---|
| `generated_at` | 2026-10-15（RuleIndex 主线精确整合专项，只读盘点补登 Rule31；保留原 Rule32/Rule33 权威正文及历史证据） |
| `base_prompt_hash` | `5aeea16c7677`（`sha256(_BASE_PROMPT)[:12]`，M1 实测 2026-10-12） |
| `lite_version` | 19 |
| `sot` | `docs/ai_rules.md` |
| `records` | 37（2026-10-15 按当前 `scripts/rule_presence_audit.py` **全文去重 ref** 口径只读实测：34 个 `RULE-AI-xx` 文本编号，**包含仅在空缺说明中提到、并非正式规则的 RULE-AI-21**，再加附则/子规则/方法层 3 条；真正以 SoT `##` 标题定义的正式 Rule 是 **33 条**，对应本台账 33 个正式规则行，另有 3 个 scope 登记项，共 **36 条真实登记项**。脚本观测 37 不得误称“正式规则 34”或“真实登记项 37”；此处只纠正台账口径，不修改盘点器实现。Rule31 在原 main 台账漏登、Rule32/33 原条目完整保留；gaps=3、uncovered=0） |
| `gaps` | 3（G1/G2/G3） |
| `uncovered` | 0（无静默跳过） |
| 观测方法 | M1 provider-view 口令扫描 / M2 hydration kind 计数 / M3 条款对齐矩阵 / M4 A-G 静态快照 |

**四态枚举**（`state ∈` 唯一）：`在 prompt` / `在库未注入` / `仅工具契约` / `仅按需水合`。
**确定性枚举**（`determinacy ∈`）：`在场` / `未在场` / `无法判定`。

## 1. M1~M4 实测值（机械观测，可复现）

### M1 provider-view 口令扫描（`_BASE_PROMPT`，只读）

| 口令 | hits | 说明 |
|---|---|---|
| `直接回答` | 0 | 终止性语义不在 universal prompt |
| `单条状态` | 0 | 等待态停止语义不在 universal prompt |
| `调整策略` | 0 | 停滞调整语义不在 universal prompt |
| `按需检索` | 1 | 唯一命中的"按需"类口令（"按需检索已验证经验/方法并核适用性"） |
| `按需水合` | 0 | 水合通道未在 prompt 显式命名 |
| `完成裁决` | 1 | 仅以**否定式**出现（"不替你制定任务策略或完成裁决"） |
| `RULE-AI` | 0 | 规则编号不在 universal prompt（INV-6/`test_rule_retrieval_contract:157`） |
| `已验证经验/方法` | 1 | 与"按需检索"同句 |

> **结论**：`_BASE_PROMPT` 对 A 组（终止性/收口）**零承载**，对 B 组仅承载"按需检索经验/方法"这一发现入口，**未承载触发时机**。

### M2 hydration `record_kind` 计数（`data/audit/injection_ledger.jsonl`，只读；基线 2026-09-23 盘点时点，运行时自然增长，当前值见 §5）

| `record_kind` | count |
|---|---|
| `memory` | 18 |
| `memory_extract` | 18 |
| `rule` | **0** |

> **结论**：复现"工具调用无一次走 `kind=rule` 水合通道"（AC-6）。`rule` 单列为 0，是 B 组"发现入口无触发时机"的直接证据。

### M3 条款对齐矩阵（SoT ↔ provider-view）

对 `RULE-AI-00`~`RULE-AI-25`（缺 21）逐条扫描：`base_prompt_hits` **全部 = 0**（M1 已证 `RULE-AI` 口令 hits=0）。故全部正文规则在 universal prompt 层为 `在库未注入`；其承载位由工具契约层 / 按需水合通道承接（见 §2）。

### M4 A-G 契约瘦身口径快照（静态，权威以 pytest 为准）

| 口径 | 状态 | 依据 |
|---|---|---|
| A-G1 必读类指令 | green | `必读/必须/禁止/严禁` 在 `_BASE_PROMPT` hits=0 |
| A-G2 运维主题（11 类） | green | 11 类运维词在 `_BASE_PROMPT` hits=0 |
| A-G3 方法层①~⑥ | green | 方法层词在 `_BASE_PROMPT` hits=0（已迁 skill） |
| A-G4 扩展通道 | green | `prompt.py` 无 `SYSTEM_PROMPT_EXTRA`/`LFL_SYSTEM_EXTRA_BUNDLE`；`build_system_prompt` 忽略 `extra` |

## 2. 全量记录（AC-1 / AC-2）

### 2.1 A 组：G1 终止性/收口决策点语义（**本特性修复**）

| rule_ref | scope | 主导承载位 | 其余承载位 | state | 观测 | 实测值 | 确定性 |
|---|---|---|---|---|---|---|---|
| RULE-AI-03 | 停滞自主调整 | `convergence_decide` schema（修复后） | `search_records` 契约 | 在库未注入 | M1 | hits=0（prompt） | 在场 |
| RULE-AI-11 | 截断提炼与轮次耗尽归因 | `convergence_decide` schema（修复后） | SoT | 在库未注入 | M1 | hits=0 | 在场 |
| RULE-AI-20 | 任务有界推进 | `convergence_decide` schema（修复后） | SoT | 在库未注入 | M1 | hits=0 | 在场 |
| 方法层①（状态追踪） | RULE-AI-00 附则 | `skills/long-task-research/SKILL.md` | `convergence_decide`（部分残留） | 仅按需水合 | M1 | 非正文条款 | 在场 |

### 2.2 B 组：G2 规则可发现性触发时机（**本特性修复**）

| rule_ref | scope | 主导承载位 | 其余承载位 | state | 观测 | 实测值 | 确定性 |
|---|---|---|---|---|---|---|---|
| RULE-AI-18 | 经验按需复用（discover→hydrate） | `search_records` 契约（修复后） | SoT | 在库未注入 | M1/M2 | prompt hits=0；`rule` hydration=0 | 在场 |
| RULE-AI-22 | 检索时序纪律 | `search_records` 契约（修复后） | SoT | 在库未注入 | M1 | hits=0 | 在场 |
| RULE-AI-24 | 开发与修复防退化契约 | `search_records` 契约（修复后） | `AGENTS.md` | 在库未注入 | M1 | hits=0 | 在场 |

### 2.3 C 组：设计性零注入（**仅登记，不主张修复**）

以下规则在 provider-view `在库未注入` 属**契约瘦身后的设计性零注入**：其语义由工具 schema / 运行时协议 / 按需水合 / skill 承载，不逐轮注入 universal prompt。

| rule_ref | 主导承载位 | state | 备注 |
|---|---|---|---|
| RULE-AI-00 | 工具契约层 | 在库未注入 | 总纲；附则①~⑥ 见 §2.4 |
| RULE-AI-01 | 工具回执（事实诚实） | 仅工具契约 | 完成诚实由回执/事实源承载，非 prompt 声明 |
| RULE-AI-02 | 工具参数 Schema | 仅工具契约 | 参数约束以机器可读 Schema 为单一真值 |
| RULE-AI-04 | 运行时容错 + `search_records` | 仅按需水合 | 程序故障处理，SOP 下沉 |
| RULE-AI-05 | `search_records`/memory | 仅按需水合 | 记忆资格按需持久化 |
| RULE-AI-06 | `self_evaluate`/演进工具 | 仅工具契约 | 子规则 1~6 见 §2.4 |
| RULE-AI-07 | 工具契约层 | 仅工具契约 | 工具优先执行 |
| RULE-AI-08 | 工具契约层 | 仅工具契约 | 观察—判断—行动闭环 |
| RULE-AI-09 | provider/model registry | 仅工具契约 | 模型切换自主（availability failover） |
| RULE-AI-10 | `architecture_status` | 仅按需水合 | 按需运行自省，非每轮清单 |
| RULE-AI-12 | 身份约束 | 在库未注入 | 身份声明约束（事故条款化） |
| RULE-AI-13 | DSH 工具链 | 仅按需水合 | SOP 下沉 |
| RULE-AI-14 | 协调通道授权 | 仅工具契约 | 外部输入授权边界 |
| RULE-AI-15 | CodeArts 工具链 | 仅按需水合 | SOP 下沉 |
| RULE-AI-16 | 缓存运行时 | 仅工具契约 | 缓存是性能事实，非任务权威 |
| RULE-AI-17 | 出口边界程序承接 | 仅工具契约 | 长内容出口无损承接 |
| RULE-AI-19 | 中断恢复运行时 | 仅工具契约 | 程序保状态，模型续推理 |
| RULE-AI-23 | 授权来源判定 | 在库未注入 | 短回复最近绑定；历史提议不得自我授权 |
| RULE-AI-25 | 委派回传/编排规模上下文经济纪律（SoT + lite v19 按需水合） | 在库未注入 | EVO-20260923-6c3aa564（2026-09-23 人工批准）新增：中间产物正文不进编排者上下文，回传默认结论+stable ref+短摘要≤200字符；模型行为纪律，无工具契约承载 |
| RULE-AI-26 | 时间标注统一宿主本地时区（SoT 2026-09-29 用户指示） | 在库未注入 | 时间权威锚=宿主本地时钟：程序层 `system_local_now()`（timekeeping），模型层消息头 `[message_time system_local=…]`；行为纪律（不推 UTC/不猜时区/不迁移旧时区），程序承载位=timekeeping 契约+消息头锚点，无 universal prompt 注入 |
| RULE-AI-27 | 任务理解章程——可证伪回显、授权隔离、纠偏即记账（SoT 2026-10-12） | 在库未注入 | EVO-20261012-e29ead3c（2026-10-12 人工批准）新增：出章程显式触发四条件+触发原因外化、可证伪验收、未纠≠认可、授权隔离（章程确认不得作为授权依据）、修订路径封闭+继承、验收条目落 Goal/task、纠偏即记账、敏感值不落章、防压缩后重放；模型行为纪律，无工具契约承载 |
| RULE-AI-28 | 三道审查闸——代码全量测试前/文章发布前/push 前独立子代理审查（SoT 2026-10-12） | 在库未注入 | EVO-20261012（用户指示 2026-10-12，入库提交 30ece512e）新增：三类高成本/难撤回动作前独立审查子代理 PASS 为必要条件，审查者与执行者分离；三态 verdict（PASS/REVISE/BLOCK）+ 回执落盘；豁免三类（用户豁免/纯文案/既有回执且 SHA 未变）如实记录；与知识体系持续优化循环衔接；行为纪律，无工具契约承载。**台账本次补登**（并行会话入库时漏登，EVO-20261012-19f88338 连带处置） |
| RULE-AI-29 | 方法/经验用后负反馈必须在当前任务收口前闭环（SoT 2026-10-12） | 在库未注入 | EVO-20261012-19f88338（2026-10-12 人工批准）新增：触发三情形（不适配/误导/时效过期）+ 三级处置（record_use 保底 / refine·annotate_freshness 修正首选 / invalidate·retire 核验后弃用）+ 证据要求（"我用不上"≠"它错了"，not_applicable 不得升级弃用）+ 收口时限（明确判定当场处置）+ Learning Plane 兜底非替代；模型行为纪律，工具契约已支撑，无新增程序角色 |
| RULE-AI-30 | Fail-closed 通用纪律——无法判定按未通过处理（SoT 2026-10-14） | 在库未注入 | EVO-20261014-483ca6de 新增：防线类机制（校验/过滤/脱敏/白名单/配额/门禁/寻址）无法匹配/解析/判断时一律按未通过并显式说明缺失事实；规则缺失≠允许、解析失败≠空值继续、解析异常走保守分支；fail-open 仅限显式声明"可用性优先"的既有位点（如 event_log 钩子链），新增防线默认 fail-closed、改默认须过演进审批。〔2026-10-14 web-carveout M3 回归期机械补登：内容取自 docs/ai_rules.md L491-496 真值源，登记缺口非本任务引入〕 |
| RULE-AI-31 | RSI 方法/经验循环：实质任务开局有界检索、实际使用后计分与生命周期处置（SoT 2026-10-14） | 在库未注入 | 权威 `docs/ai_rules.md` 规则三十一：有实质多步/工具任务时 `search_records` 从 method/experience/lesson 最多选2类、每类≤5，同连续任务窗口只检索一次；简单问答/闲聊豁免，零命中不循环换词。稳定 ref 用于精确水合，命中时效与任务适用性由模型判断；实际引用后的 `record_use` 正负评分与处置遵循既有工具契约，程序不代替模型做语义判断，不无条件向 universal prompt 注入经验/方法。2026-10-15 从当前 main 精确整合时补充正式台账行，主线 Rule32/33 保留。 |
| RULE-AI-32 | 共享文件格式化纪律——禁全文件 ruff format，hunk 级最小化或独立提交（SoT 2026-10-14） | 在库未注入 | EVO-20261014-a731be2b 人工批准新增：对非本次任务新引入的共享/存量文件禁止 `ruff format <file>` 全文件重排；格式化只允许作用于本次任务实际新增/修改的 hunk；确需全文件 format 时先 `ruff format --diff` 评估并独立提交（不与语义改动混提）；动机=M1b 实测全文件重排引入 ~400 行噪声污染审查面（ANALYSIS §7 实施纪律记录）；程序角色=无新增（规则层条款化，RULE 卡检索命中）。〔2026-10-14 可观测性 M1c-rev 全量回归期机械补登：内容取自 docs/ai_rules.md L527-535 真值源，登记缺口非本任务引入〕 |
| RULE-AI-33 | service_control generation 冲突即事实——冲突回执直接重试、显式带代（SoT 2026-10-14） | 在库未注入 | 2026-10-14 终审组合实施同步登记（非漏登，SoT 规则三十三）：模型侧调用纪律条款——generation 冲突回执即当前事实，直接以回执 current 重试（存活 owner ≤一 poll；死 worker 由 reaper 按 30s/120s/2100s 分档回收），不等待/不询问；首选显式 expected_generation=最新 status 观察值；等待中旧 action 不构成重试前置；A 方案（publish 时全量 supersede 非终态 action）rejected 留档于条款第 4 条。程序角色=程序侧已实现（等待循环 stale 检测 + reaper accepted 覆盖，同一变更集），规则只管模型侧。 |

> RULE-AI-22 同时出现在 §2.2（B3 子缺口：discover→hydrate 触发时机）与本节（主条款设计性零注入），二者不冲突：本特性只补"触发时机"子语义，不改主条款。

### 2.4 scope 分区登记（非正文条款）

| 条目 | scope | 主导承载位 | state |
|---|---|---|---|
| RULE-AI-00 附则①~⑥ | 方法层总则 | `skills/long-task-research/SKILL.md` | 仅按需水合 |
| RULE-AI-06 子规则 1~6 | 演进/自评执行细则 | `skills/long-task-research/SKILL.md` | 仅按需水合 |
| 方法层①~⑥ | 状态追踪/前置自问/假设先行/增量推理/结论固化/工具轮三句 | `skills/long-task-research/SKILL.md` | 仅按需水合 |

## 3. 缺口归纳（AC-4）

| gap_id | category | 关联 records | 能力下降假设（可证伪） | 承载位裁定 | 可行动 |
|---|---|---|---|---|---|
| G1 | 终止性/收口决策点语义缺失 | RULE-AI-03/11/20 | 决策点当轮契约未承载"可调整策略/直接回答/等待态可停止"，模型停滞时无终止线索 → **漂移/重复/不收口** 上升 | `convergence_decide` schema | 是（已修复） |
| G2 | 规则可发现性缺触发时机 | RULE-AI-18/22/24 | 通道存在但契约未说明"何时该查"，`rule` hydration=0（M2）→ 事实不足时继续空转 | `search_records` 契约（每轮在场） | 是（已修复） |
| G3 | 收口出口在工具契约层缺席 | RULE-AI-01/20 | 收口只能以"不调用任何工具"表达，程序不可观测、审计不可锚定，R2 事实无挂载点 | `convergence_decide decision=conclude` | 是（已修复） |

**判定依据**：`ObservationEvidence`（M1 口令 hits / M2 kind 计数 / M3 对齐矩阵 / M4 A-G 快照）见 §1。

## 4. 上位机制映射（AC-12 / AC-14）

| 上位机制 | 与 `rule_presence` 关系 | 说明 |
|---|---|---|
| R1 唤醒事实段 | 依赖（只引用不实现） | G1 文案不输出"任务已失效"等程序结论（AC-12）；唤醒事实属 R1 范围 |
| R2 回执机械事实三件套 | 衔接（同承载位、字段并列、不实现） | 本特性仅产"自陈段 + 非完成裁决标注"；R2 事实段组装点**待与 R2 实现方对齐**（`execute` 内无 vitals/历史/队列上下文） |
| R3 | 互补 | 无重叠承载位 |
| R4 | 互补 | G2 明确"按需、非强制、不强制顺序"缓解时机语义过宽 |
| R6 | 独有 | 本特性为规则在场性唯一盘点产物 |

**冲突记录**：当前无冲突。若任一文案与 antidrift SPEC 冲突，以 SPEC 为准并在此登记。

## 5. 回归台账（任务 1.1 / 5.4，禁扩基线）

| 项 | 结果 |
|---|---|
| 基线（改动前）：`test_model_contract_slimming.py` + `test_ai_rules_sync.py` + `test_rule_retrieval_contract.py` + `test_convergence_boundary.py` | 35 passed（全绿） |
| `test_rules_version_reflects_v18`（`test_model_contract_slimming.py:246-260`） | green |
| A-G1 / A-G2 / A-G3 / A-G4 | green（无一项判定为"需放宽"） |
| 改动后回归：分组2（F1/F2） | 17 passed |
| 改动后回归：分组3（F3/F4/F5） | 34 passed |
| 改动后回归：分组4（F6/F7） | 14 passed |
| 改动后回归：新增 `test_rule_presence_contract.py` | 18 passed |
| 改动后回归：全量 `tests/unit` | **EXIT=0（全绿，无新增红）** |
| 重新盘点（2026-09-23）：lite v18→v19 / RULE-AI-25 入库补登记 | 触发 §6 条件 2；`rule_presence_audit.py` 实测 `records=28`、`base_prompt_hash=8934d96c3f25` 未变、hydration `memory/memory_extract=18/18`；`test_rule_presence_contract.py` 18/18 绿 |
| 重新盘点（2026-10-12）：RULE-AI-27 入库补登记 | EVO-20261012-e29ead3c（人工批准）执行；`rule_presence_audit.py` 实测 `records=31`、`gaps=3`、`uncovered=0`、`base_prompt_hash=5aeea16c7677`、lite v19 未变；`test_ledger_covers_all_sot_rules` 修复后绿（详见本轮回归记录） |
| 重新盘点（2026-10-12）：RULE-AI-28 台账补登 + RULE-AI-29 入库 | EVO-20261012-19f88338（人工批准）执行；`rule_presence_audit.py` 实测 `records=33`、`gaps=3`、`uncovered=0`、`base_prompt_hash=5aeea16c7677` 未变、lite v19 未变（hydration kind 计数为运行时数据自然增长：memory/memory_extract=70/70、method=24，非本次改动所致）；`test_ledger_covers_all_sot_rules` 覆盖 28/29 后绿 |
| 重新盘点（2026-10-15）：Rule31 当前 main 精确整合与库存口径核对 | 以 `main@2ad0bc06d55aefa3496bdf8c26bad1a4dc2963b2` 的 SoT 为源只读盘点：脚本 `records=37`、`gaps=3`、`uncovered=0`、`base_prompt_hash=5aeea16c7677`、lite v19；交叉核验 SoT 正式 H2 Rule=33（00–20、22–33），正式台账行=33、附属 scope=3（合计36）；脚本使用全文 `RULE-AI-\d{2}` 去重，额外把正文中的空缺号 RULE-AI-21 记入，故报告 37。该差异已显式披露为盘点口径问题，未调整盘点算法、未新增/删除规则、未放宽测试；测试与审查资格以各自正式回执为准，不得由本盘点行代替。 |
| 已知红处置 | 无新增已知红；既有已知红仍为"修复 或 显式接受"，**未扩基线** |

## 6. 重新盘点触发条件

满足任一即重新运行 `scripts/rule_presence_audit.py` 并更新本台账：

1. `_BASE_PROMPT` 内容哈希（`base_prompt_hash`）变更；
2. `docs/ai_rules.lite.md` 版本变更（当前 `version=19`）；
3. 任一落点工具契约变更（`convergence_decide` / `search_records`）；
4. 事故复盘发现新的"规则在库、不在场"缺口。

## 7. 形态与安全约束声明

- **只读**：盘点不写任何被测对象；`M1/M3` 为纯文本扫描，`M2` 为只读 JSONL 聚合（AC-17）。
- **fail-open**：观测失败输出 `无法判定` + 原因，不默认归为缺席/在场（AC-7），不抛断整体盘点。
- **非 CI 硬门**：不接入 CI，不作为 build/test 阻塞项（用户裁定 #4）；若未来转门禁须另行论证"模型 + 现有工具无法自判"。
- **无敏感信息**：本台账不写凭证、密钥或私有绝对路径（spec §4.3.1）。
## 8. 治理自洽审查（AC-11）

**准入不对称判定**：本特性三处机制均为**放大模型能动性**，非新增控制机械。

| 机制 | 判定 | 论证 |
|---|---|---|
| G1 决策点语义（F1/F2） | 放大能动性 | 纯附加文本；让模型在停滞时看见"可调整/可直接回答/可停止/可按需水合" |
| G2 触发时机（F6/F7） | 放大能动性 | 纯附加文本；让模型知道"何时该查规则"，通道本已存在 |
| G3 `conclude` 出口（F3/F4/F5） | 放大能动性 | 新增**模型可用的表达动作**；程序不解码语义、不判完成 |

**控制机械四类否证（G3）**：

1. 硬门禁 ❌：不阻断调用、不终止 run、不限制轮数；
2. 启发式裁决 ❌：程序不解码 `conclude` 语义、不做相似度、不判 `complete`；
3. 静默截断 ❌：无截断；
4. 兼容层 ❌：`continue` 语义零变更，无兼容分支。

**G3 的 5 条模型可调用出口（逐条成立）**：

1. 不调用工具（保持原有"直接回答"路径）；
2. `decision=continue`（保持既有语义）；
3. 直接回答（仍为主要落地路径）；
4. `conclude` 后继续调用普通工具（边界已复位，INV-3 端到端验证）；
5. 忽略自陈（无状态锁定，INV-1 零状态变更）。

**基础设施核验**：未引入外部协调器、分布式锁、新持久化引擎或新状态机。
**承载位核验**：全部落白名单（工具契约层 F1~F7；operator surface 盘点器）。

## 9. 端到端验证结论（AC-16 / tasks 6.5）

| 链路 | 结论 | 证据 |
|---|---|---|
| 边界轮只暴露 `convergence_decide` | 保持 | `test_convergence_boundary.py:101/140/200/230-231` |
| `conclude` → 边界释放 → 普通工具面恢复 | 成立 | `test_conclude_releases_boundary_and_reopens_normal_tool_surface` |
| `conclude` 零状态变更、非完成裁决 | 成立 | `test_conclude_does_not_mutate_goal_task_session_state` / `..._has_no_completion_verdict_words` |
| 非边界轮 `search_records` 已含时机语义 | 成立 | `test_search_records_contract_carries_timing_semantics`（lazy 默认面） |
| 台账与盘点器实测值一致 | 一致 | §1 由 `scripts/rule_presence_audit.py` 实测产出 |