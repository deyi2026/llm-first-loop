# Q5 语义判断归属审计清单（Semantic Authority Audit Checklist）

| 项 | 值 |
|---|---|
| 状态 | draft-for-review（清单已就绪；**本文档不含代码改动**） |
| 建立日期 | 2026-09-26（2026-09-26 判据升级为三层） |
| 性质 | 可逐项执行的审计清单（evidence-first，**不是门禁**） |
| 判据一 | `docs/DEVELOPMENT_REPAIR_SAFETY.md` §1 Q5 + §2.8/2.18（负向禁令） |
| 判据二 | `docs/DESIGN-20260926-model-variance-containment.md` 三层模型 A/B/C（正向归类） |
| 关联 | `docs/LEDGER-20260926-compat-retirement.md`、`docs/SPEC-20260922-run-convergence-antidrift-v1.md`、`docs/ANALYSIS-20260924-authority-map-refusal-audit.md` |
| 证据口径 | 2026-09-26 工作区实测（`ahead 120`，27 tracked `+2194/-223`） |

---

## 0. 目的与判据升级

`LFL` 的宪法是「**程序保真、保边界、保可恢复；模型做语义、策略、取舍、完成判断**」。最大的隐性风险不是缺功能，而是**程序在无意识中重新变成第二大脑**。

**本清单的判据 = Q5（负向禁令）× 三层（正向归类）**：

- Q5 回答"程序**不该**做什么"；
- 三层回答"某个含语义的机制**该长期保留、改造，还是下放**"。

**关键读法（2026-09-26 升级的核心）**：

> **"含语义"不再等于"该退役"。** 只有「**纯策略结论 + 无 model-invokable veto 出口**」才退役；
> 「事实形态的稳定器（B 层）」应**长期保留并硬化输出契约**。

理由见 `DESIGN-20260926` §0：可靠性是系统属性，不能外包给模型自省；把"语义参与"整体当包袱删除，会重新引入漂移、重复、错误完成与不收敛。

---

## 1. 判据一：Q5 两列（审计时逐字对照）

| 程序**可以**判断（机械事实） | 程序**不应**判断（语义裁决） |
|---|---|
| 字节 / token / 内存是否物理装不下 | 哪段语义"重要" |
| ref 是否存在、SHA 是否匹配 | 哪个历史片段"应该进入 prompt" |
| 当前是 queued/running/cancelled/completed | 当前任务"已经完成" |
| source 是否完整、offset 是否前进 | 哪段 reasoning"值得自动 replay" |
| 安全、授权、数据完整性和真实资源边界 | 什么时候"应该自动总结" |
| — | 哪个模型"语义上更适合"（未经模型/用户决定） |

**口诀**：程序保真、保边界、保可恢复；模型做语义、策略、取舍、完成判断。

**关键区分**：
- "物理装不下所以分页" = 合法（机械边界）。
- "这段历史不重要所以丢弃" = 违规（语义裁决）。
- "逐字镜像全部历史，超预算从最旧截断" = 合法（机械邻近，`SPEC-20260922` §5 A）。

---

## 2. 判据二：三层归属（决定"保留还是下放"）

完整定义与命名告诫见 `DESIGN-20260926` §1。摘要：

| 层 | 名称 | authority | 输出形态 | 判据 |
|---|---|---|---|---|
| **A** | 不变量 | 程序（机械） | 可判定事实 / 硬边界 | 不依赖语义 |
| **B** | 稳定器 | **无**（只供事实） | **事实句 + 可计数 + 可否决** | 输出事实，不输出结论 |
| **C** | 模型裁决 | 模型 | 策略 / 取舍 / 完成 | 由模型作出 |

**两条硬规则**：
1. B 层合法性挂在**执行期输出字符串/字段**上，不挂在模块名上（`DESIGN` §2）。
2. 收敛**保证**只能落在 A 层；B 层只提升收敛**概率**，不得声称"保证收敛"（`DESIGN` §3）。

---

## 3. 审计方法与裁决四态

对每个候选机制依次问五问（第 5 问为 2026-09-26 复核补充，堵住"C 伪装成只读分数"）：

1. **它输出的是"事实/边界"还是"语义结论"？**（判据一右列）
2. **它属于 A / B / C 哪一层？**（判据二）
3. **若含语义，能否替换为「逐字镜像 + 机械预算/邻近」？**
4. **若确需保留判断，是否提供 model-invokable veto 出口？**
5. **它的"事实"是怎么产生的？生成过程本身是否需要程序做任务语义判断？**（若需要，即使只读也是 C；见 `DESIGN` §2.1-5）

| 裁决 | 层级归宿 | 含义 | 动作 |
|---|---|---|---|
| **保留为不变量** | A | 纯机械事实 / 边界 | 补回归测试钉住形态 |
| **改造为稳定器** | B | 有语义成分，改造为"事实句 + 可否决" | 去掉结论/祈使字段，保留并强化可计数事实 |
| **下放给模型** | C | 应属模型裁决 | 移除程序结论，事实留给模型 |
| **退役** | — | **纯策略结论且无 model-invokable veto 出口** | 删除，登记 `LEDGER` |

> 原四态中的"收敛/降级为事实"已被本表吸收：**收敛 → 改造为稳定器（B）**；**降级为事实 → 改造为稳定器（B）**。退役口径被收窄（新增"纯策略结论"限定）。

---

## 4. 审计主表

### 4.1 已合规基线（正确形态参照，须防回归）

| ID | 机制 | 层级 | 证据 | 为何合规 |
|---|---|---|---|---|
| Q5-B1 | 工具可见性 = 环境机械事实，非语义选择 | A | `tools/eligibility.py:1-7,33-46` | P1-B 已退役 R8.7 semantic selection plane；关键词永不决定可见性 |
| Q5-B2 | round schema 投影丢弃语义输入 | A | `core/loop/engine_services/tool_cycle.py:908-921` | `planned_label/user_text/session_messages` 被 `del`，零权威 |
| Q5-B3 | `tool_history` 为有界投影，无阻断消费 | B | `core/loop/engine_services/tool_cycle.py:879-889`；`introspection/status.py:260-265` | 环形缓冲 `[-200:]`，arguments 丢弃；仅只读展示 |
| Q5-B4 | convergence_boundary 不做完成判定 | B | `core/loop/engine_services/convergence_boundary.py:1-8,24,35,45-51` | docstring "never decides that the user's task is complete"；只 arm + 回事实 |
| Q5-B5 | convergence_decide 回执附机械事实 | B | `SPEC-20260922` §5 A（裁定）；`core/loop/engine_services/tool_cycle.py:935-937` | 全量历史逐字镜像 + 预算封顶 + 从旧截断；程序零相似度计算 |
| Q5-B6 | duplicate/stagnation guard 仅 shadow 观测 | B | `config.py`（`LFL_DUPLICATE_GUARD_MODE=shadow`）；`SPEC-20260922` §2.2 F6 | 只观察不阻断；enforce 被显式否决（§5 E） |
| Q5-B7 | memory 自动注入退役（仅保读字段） | A（纪律） | `memory/store.py:49-50` | 不再由程序决定"注入哪条记忆" |
| Q5-B8 | program_recovery 退役 | A（纪律） | `core/program_recovery.py:1-6` | 仅保留识别/清洗 |
| Q5-B9 | prompt `extra` 参数弃用 | A | `core/prompt.py:13-21` | `del extra` |

### 4.2 待审计项（按疑似程度排序；"目标层"为初步判断）

| ID | 机制 | 证据 | Q5 疑点 | 目标层 / 契约动作 |
|---|---|---|---|---|
| Q5-A1 | run 压缩 `run.compact` / `fixed_summary` / `summary_chain` | `SPEC-20260922` §1（161,401→62,995 chars）；`core/history.py` | 程序决定"何时压缩、丢哪些历史" | **B**：改为机械预算 + exact source 存档；保留可回读事实 |
| Q5-A2 | 压缩后工作面的片段取舍 | `SPEC-20260922` §2.1 F4 | 任务源 prompt 被淘汰、未保真回注 | **B**：R3 任务源压缩豁免（cap=1，机械）+ 输出"起源 ref 仍可回读"事实 |
| Q5-A3 | `history_anchors` | `SPEC-20260922` §2.2 F11 | 是否为任务语义锚？ | **A**：核实为前缀缓存锚，与任务语义无关 |
| Q5-A4 | recent dialogue working set | `DEVELOPMENT_REPAIR_SAFETY.md` 2.3；commit `9766aee` | 窗口是否机械？ | **B**：确认按机械邻近保留，非语义挑选 |
| Q5-A5 | convergence_decide 自身历史镜像 | `SPEC-20260922` §4 R2 | 是否程序挑"前 K 次"？ | **B**：已裁定（全量 + 从旧截断） |
| Q5-A6 | tool_guidance 三态 | `config.py:47,818-820`；`tools/registry.py:180-204,1427-1440` | 建议是否程序语义生成？ | **A/B**：确认建议为静态规则或已退役 producer |
| Q5-A7 | Evidence enforce / ERC rollout | `config.py:343-344,244-256`；`factory.py:682-904` | 是否判断"证据是否充分"？ | **A**：钉死为机械 ref/SHA/覆盖校验，输出事实句 |
| Q5-A8 | knowledge injection ledger | `knowledge/injection_ledger.py:11,26` | 注入决策是否程序语义？ | **A**：确认 ledger 只记录、不裁决注入 |
| Q5-A9 | cognitive / COG runtime Decision Packet | `config.py:413-425`；`core/loop/build.py:640-677` | 决策包是否替模型组织语义？ | 先裁决 `LEDGER` H1（代码 shadow vs 文档退役） |
| Q5-A10 | task_quality | `subsystem-disposition-20260909.md` §2 | 预判"启发式裁决重灾区"；**实测非 C** | **待判定（不预设 B）**：按五检拆 A/B/C，见 §10 |
| Q5-A11 | cache_guard | `subsystem-disposition-20260909.md` §2 | 预判同上；**实测无 C**，A+B 混合 | **已裁决（见 §10）**：privacy=A；`submit_ratio`(on)=退役；其余=B |
| Q5-A12 | SelfEvaluator 效率指标 | `introspection/evaluator.py:226-250` | 是否形成阻断？ | **B**：确认只读展示、无阻断消费 |
| Q5-A13 | semantic retrieval RRF 融合权重 | `memory/retriever.py:917-929` | 排序是否算语义裁决？ | 放大器（保留）：确认不决定"哪段进 prompt" |
| Q5-A14 | RG-3C provider settlement shadow | `resources/provider_calls.py:84-158`；`resources/ledger_projection.py:297,803` | 影子账是否第二语义权威？ | **A**：确认影子只做对账、不作裁决 |
| Q5-A15 | prompt eligibility 观察期计数 | `core/prompt_eligibility.py:58-65` | 残留程序判定"该不该给"? | **退役**：观察期结束删除 `would_have_granted` |
| Q5-A16 | multiquery 融合 | `config.py:259-271`；`memory/multiquery_shadow.py:34` | 是否程序决定查询改写？ | **B**（shadow）：确认不改写语义、只扩展召回 |

### 4.3 已识别缺口（`SPEC-20260922` 事故驱动，待实现后复核）

| ID | 缺口 | 证据 | 目标形态（已裁定） |
|---|---|---|---|
| Q5-C1 | convergence_decide "自写自批"：输入无机械事实 | `SPEC-20260922` §3 P2 / §2.2 F8 | **B**：R2 回执附 run vitals + 全量历史镜像 + 队列压力 |
| Q5-C2 | 任务源消息被压缩淘汰，再锚定不可能 | `SPEC-20260922` §3 P3 / §2.1 F4 | **B**：R3 活跃任务源压缩豁免（cap=1） |
| Q5-C3 | 变体探索无观测口径 | `SPEC-20260922` §3 P8 / §2.2 F6 | **B**：保留 shadow；**否决**语义相似度（§5 E） |

---

## 5. 高优先审计项（本周期 Top 5）

1. **Q5-A1 + Q5-A2（压缩语义）** —— 最易复发：程序决定"何时压缩、丢什么"。须证明为"机械预算 + exact source 存档"，并补任务源回注（R3）。
2. **Q5-A7（Evidence enforce）** —— 若被做成"程序判断证据是否充分"，直接违反 Q5；钉死为机械 ref/SHA/覆盖校验。
3. **Q5-A9 + LEDGER H1（COG Runtime）** —— 先解决"代码 shadow vs 文档退役"不一致，再审计 Decision Packet。
4. **Q5-A10 + Q5-A11（task_quality / cache_guard）** —— **三层模型的破坏性测试（均已完成，见 §10）**：不预设"改成只读 evaluator"；按五检拆分，两项均**未发现 C 型语义裁决**，争议各自落在"未接线模块"与"性能政策代理"上。
5. **Q5-A6 / Q5-A15** —— 建议面与观察期残留最容易重新长成语义控制。

---

## 6. 逐项裁决记录模板

审计每项时在下方追加一条（**先取证，再裁决**，`DEVELOPMENT_REPAIR_SAFETY.md` §1）：

```
### Q5-Ax  <机制名>
- 审计日期：
- 实际行为（provider-visible 输出字符串 / 代码事实）：
- Q5 疑点命中：判据一右列第 __ 条
- 三层归属：A / B / C
- 证据：<文件:行>
- 输出契约检查（B 层五检）：可计数 ☐ / 无结论 ☐ / 可追溯 ☐ / 模型可否决 ☐ / 来源机械（生成无需程序语义判断）☐
- A/B/C 成分拆分：A=____ / B=____ / C=____
- 裁决：保留为不变量 / 改造为稳定器 / 下放给模型 / 退役
- 若保留判断：为什么模型+现有工具不能自判？
- model-invokable veto 出口：
- 验收：<失败不变量 / regression test>
- 关联 commit：
```

---

## 7. 执行节奏

1. **先审 Top 5（§5）**，每项产出 §6 记录；不合并不同机制的审计（`DEVELOPMENT_REPAIR_SAFETY.md` 2.15）。
2. **裁决为"改造为稳定器/下放/退役"的项**：先写失败不变量（RED），再改实现，再跑 focused gate。
3. **裁决为"保留为不变量"的项**：补回归测试钉住形态，防止未来重构时无意中把它变成语义裁决。
4. **小模型压力测试（`DESIGN` §4）**：对 B 层机制，用"最弱可支持档"复测，按**三分归因**（能力下降 / 稳定器缺口 / 事实可用性缺口）出结论；第三类必须回改呈现契约。
5. **与 `LEDGER` 联动**：退役项登记 `LEDGER`；新增 A/B 机制登记并附 veto 出口。
6. **验证口径**：最终 gate 在 staged/isolated candidate 上执行（Q6）；运行态验证 `source config → live process → backend actual request` 三层一致（Q4）。

---

## 8. 验收标准

- [ ] §4.2 全部 16 项均有 §6 裁决记录，且标注 A/B/C 层。
- [ ] 所有 B 层机制的执行期输出通过契约五检（可计数/无结论/可追溯/可否决/来源机械）。
- [x] A10/A11 已形成 §10 裁决记录，且**未预设层归属**（两项均无 C，见 §10）。
- [ ] §5 Top 5 全部闭环：A1/A2 有"机械压缩 + 保真回注"证据；A7 钉死机械校验；A9/H1 已裁决；A10/A11 改造为 B；A6/A15 处置完成。
- [ ] 无任何机制在 Q5 右列语义处新增程序结论字段（代码审查项）。
- [ ] 已合规基线（§4.1）全部有回归测试，回退即红。
- [ ] 至少一项 B 层机制经"最弱可支持模型"复测，并按三分归因出具结论。

---

## 9. 明确不做

- **不因"某机制含语义"就判退役**（本清单 2026-09-26 升级口径，§0）。
- 不用 B 层事实替代 A 层硬边界来"保证"收敛（`DESIGN` §3）。
- 不把 B 层实体化为新的 containment subsystem（`DESIGN` §1 命名告诫）。
- 不新增近似重复的语义相似度计算（`SPEC-20260922` §5 E）。
- 不为"可解释"把语义判断从模型搬回程序（`subsystem-disposition` §0）。
---

## 10. 裁决记录（滚动追加）

> 按 §6 模板逐项追加。**不预设层归属**；一个机制可被拆成 A+B+C 成分。
> 取证口径：2026-09-26 工作区实测（ahead 120，27 tracked `+2194/-223`）。

### Q5-A10  task_quality

- 审计日期：2026-09-26
- 机制：`task_quality` 子包（`src/llm_loop/task_quality/`，2194 行，声明六路径 A/D/E/H/I/K）
- 实际行为（代码事实）：
  - 运行时**只接线两条**：A = `PreCheckLayer`（`factory.py:2230-2234`）、I = `FixLoopTool`（`factory.py:2236-2245`，H `ErrorLocator` 作为 I 内部组件）。
  - D/E/K（`StaticCheckChain` / `ConventionExtractor` / `DepGraph`+`RegressionGuard`）**零装配、零消费**：仅测试与自身模块引用。
  - **无 0.0~1.0 质量分、无 `score`/`quality`/`should` 字段、无 LLM/embedding/语义相似度调用**。
  - 唯一 enforce = 路径 A 参数 Schema 预检：不合法则跳过工具执行（`registry.py:979-991`），依据自实现 JSON Schema（类型/必填/enum），**无需任务语义**，fail-open（`precheck.py:64-74,84-86`）。
  - 修复语义已下放子代理 LLM：程序只拼任务文本（`fix_loop.py:238-244`），不产出完成/质量结论。

- 三层归属与五检：

  | 成分 | 证据 | 层 | 五检（生成过程是否需程序语义判断） |
  |---|---|---|---|
  | 参数 Schema 预检 | `precheck.py:54-167`；`registry.py:979-991` | **A**（唯一 enforce，机械硬边界） | 递归 schema 校验，机械 ✓ |
  | fix_loop 熔断/计数 | `fix_loop.py:170-191,255-260` | **B** | SHA256 指纹 + 同指纹计数，机械 ✓ |
  | error_locate 定位 | `error_locate.py:34-159,189-203` | **B** | 正则抽取失败位置，机械 ✓ |
  | convention 比例判定 | `convention.py:186-276` | **B**（未接线） | 0.5/0.3 风格比例，机械启发式 ✓；但 `check_violations` 输出"违背"结论句且**零调用** |
  | D/E/K 注入与回执 | `static_check.py` / `convention.py` / `regression.py` | —（未接线） | 不适用 |
  | 修复策略 | `fix_loop.py:238-244` | **C**（已下放子代理） | 程序零语义结论 ✓ |

- Q5 疑点命中：判据一右列**无命中**（未见"质量/重要/完成/该不该"判断）。
- 裁决：
  1. **A（precheck）→ 保留为不变量**：机械 schema 门禁、fail-open、可机械复现。动作：补回归测试；记录开关默认（静态 `False` `config.py:501`；本机 `.env` `PRECHECK_ENABLED=1`）。
  2. **B（fix_loop / error_locate / convention）→ 保留为稳定器**：硬化输出契约；`convention.check_violations` **若未来接线必须先去掉结论句**，改为"比例事实"。
  3. **C → 已下放**，无需动作。
- **与预判差异（关键）**：`subsystem-disposition` §2 预判 task_quality 为"启发式裁决重灾区 / C 伪装 A"；实测**未发现任何 C 型评分**，"重灾区"所指启发式集中在 `convention.py` 且**运行时未接线**。→ 预判应更正为 **"A+B 混合"**，而非 C。
- 遗留必答项：
  1. **D/E/K**：既未接线也未登记退役，属悬置态 → 决定"接线"或"按 `LEDGER` 退役"。
  2. **precheck 的 A 形态**：确认保留为 A 硬边界，还是改造为"事实提示 + 模型可否决"。
- 验收：precheck 回归测试；`convention.check_violations` 接线前契约检查；D/E/K 处置登记 `LEDGER`。
- 关联 commit：无（本轮未改代码）。
### Q5-A11  cache_guard

- 审计日期：2026-09-26
- 机制：`cache_guard` 子包（899 行：`guard.py` 827 + `__init__.py` 11 + `mcp_server.py` 61）
- 实际行为（代码事实）：
  - 7 类规则（docstring `guard.py:1-16`）判定**全部机械**：字节/长度差、role 位置计数、`len(content)`、计数器、正则、比例、TTL/epoch 相等。
  - **无 C**：无 embedding/LLM/相似度/语义评分；第 5 检逐条为"否"。低命中**从未**被解释成"回答质量风险"（仅解释为成本/前缀漂移）。
  - BLOCK 返回点仅 3 个：`privacy_leak` 正则（`guard.py:309-313`）、`privacy_leak` env 子串（`guard.py:318-322`）、`submit_ratio`（仅 `_PERF_BLOCK_MODE=="on"`，`guard.py:281-289`）。
  - 默认 `enforce` 下 `submit_ratio` 为 WARN + `would_block` 观测（`guard.py:239-257`）；规则 A–D/G 全部只 WARN。

- 三层归属：

  | 成分 | 证据 | 层 |
  |---|---|---|
  | `privacy_leak` BLOCK | `guard.py:299-323`；`client.py:1568-1571` | **A**（唯一仍生效的硬边界：安全/数据完整性，机械正则+子串） |
  | `submit_ratio` BLOCK（`on` 模式） | `guard.py:281-289` | **A 形态 / 实为政策代理**：依据内部 history budget 95%（`engine.py:1443`），非 provider 物理窗口 → 应退役 |
  | rules A/B/C/D WARN | `guard.py:144-208` | **B** |
  | `submit_ratio` enforce 全路径 + `would_block` | `guard.py:234-295` | **B** |
  | rules G 全 WARN 分支 | `guard.py:618-728` | **B** |
  | `_classify_cache_transition` / `record_result` / `snapshot` | `guard.py:499-554,446-497,565-603` | **B**（`snapshot` 经 `status.py:754`→`architecture_status` 模型可见，内容全为计数事实） |
  | fail-open | `guard.py:371-373` | **A 纪律** |
  | C | — | **无** |

- 裁决：
  1. **A（`privacy_leak`）→ 保留为不变量**：符合 `ANALYSIS-20260831` P0-4「KEEP SECURITY BLOCK」。动作：收窄正则 + 占位豁免/熵；**扩大扫描面**（现仅 `content` 前 3 条，未扫 `tool_calls.arguments`/`reasoning_content`，与规则 F 的 `dict_wire_chars` 口径分叉）。
  2. **A 形态政策代理（`submit_ratio` on）→ 退役**：符合 P0-4「DELETE PERFORMANCE BLOCK」；默认 `enforce` 已把它降为 B（观测）。
  3. **B（其余）→ 保留为稳定器 + 硬化契约**：去除 detail 祈使/诊断结论（`guard.py:162,194,206,286-288,676-680,692-695,705-714`）；清理恒空的 `block_streak`（`guard.py:805-818` 不可达死分支）；`WARN→模型注入` 为空实现（`client.py:1565-1567` 自读自写无消费），删除或实现。
  4. **C → 无**。

- **关键运行态发现（Q4 三层一致缺口）**：`data/audit/guarded_requests.jsonl`（67,735 request）显示 `submit_ratio` BLOCK 211 次（最近 2026-09-24）与 `submit_ratio_perf` WARN 同日并存。原因：`_PERF_BLOCK_MODE` 是 **import-time 冻结的模块常量**（`guard.py:48,61`），长驻进程不感知 `on→enforce` 切换（commit `6a137efd6`）。→ **代码默认 enforce ≠ 所有 live process 实际 enforce**；必须按进程核对，不能只看 `.env`/`runtime.toml`。
- 其他缺口：
  - `CACHE_GUARD=0` 关闭开关**声明未实现**（全仓无读取，仅注释 `client.py:872-873`）→ 文档漂移；
  - 规则 G BLOCK 分支 + escape（`_BLOCK_ESCAPE_MAX`）**不可达死代码**；
  - `mcp_server.py:36` 自述"5 类规则"，实际 7 类 → 文档漂移。
- **与预判差异**：`subsystem-disposition` §2 预判"启发式裁决重灾区 / 收缩"；实测**无语义裁决**，争议集中于 `submit_ratio` 一条性能代理（且默认已降为观测）。→ 预判应更正为 **"A+B 混合；性能面退役已基本完成，剩收口"**。
- 验收：privacy 扫描面/正则改进 + 回归；`submit_ratio` on 退役；死代码清理；`_PERF_BLOCK_MODE` 改运行期解析（Q4）。
- 关联 commit：无（本轮未改代码）。