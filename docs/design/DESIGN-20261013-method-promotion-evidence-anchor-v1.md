# Method 晋升证据锚点：需求 · 设计 · 实现（v1）

- 日期：2026-10-13（Asia/Shanghai）
- 状态：**设计定稿，未执行任何代码/数据变更**。§6 全部标 NOT RUN。
- 与用户原提案的关系：**结论被拷问推翻并替换**。原提案是「给晋升补 held-out 重放门」；本文的裁决是**不做重放门**，改为 R1（promotion 与 verdict 耦合）+ R2（证据独立性），并把 held-out 重放降级为带前置条件的 R4。原提案中被保留的部分只有 ②（跨能力回归），且被重新定标为成本 2 张卡而非 892 张。
- 评审方式：`grill_me` 拷问（记录见 §4，含过程诚实声明）
- 自我核验（吃 R1 狗粮）：
  - (a) 适用信号：要动 method 池晋升资格、qualification 记录契约、或 promote-to-active 流程时
  - (b) 本文档不管：单张卡正文的对错；R3 三轴失效判定（`docs/governance/card-lifecycle.md` R3）；检索融合参数
  - (c) 核验方法：`python3 -c` 遍历 `data/methods/*/qualification.jsonl` 统计 verdict/promotion/evidence_refs 交叉分布；`grep -h '^status:' data/methods/*/METHOD.md | sort | uniq -c`；`grep -n 'promotion == "pass"' src/llm_loop/methods/store.py`

---

## 1. 背景与问题定义

### 1.1 用户命题

用户判断：method 晋升没有 held-out 重放；又因 ②（晋升要验证没碰坏别的能力）被识别为**集合级共同缺口**（comparand 全家都有这问题），故「单点最值得做」的判断变强。

本文逐条检验这个加强论证，并在 §4 记录**它被推翻的过程**。

### 1.2 实测症状（2026-10-13 本会话实测，非推断）

| # | 症状 | 机械证据 |
|---|---|---|
| S1 | **同一记录内自我否定**：73 条 qualification 中 53 条（72.6%）是 `promotion=pass` 且 `verdict=not_evaluated`。模型在同一行里既声明「值得晋升」，又记录「结果未评估」。 | 遍历 `data/methods/*/qualification.jsonl` 交叉统计 |
| S2 | **59 张卡共用一条证据**：59 条 qualification 的 `evidence_refs` 全部是同一个 `eval:SE-20260923-001-dce6`，覆盖 59 个不同 method 卡。该 ref 解析为一条**24h 窗口聚合指标**（`success_rate=1.00 / tool_efficiency=0.95 / honesty_rate=0.84 / stagnation_rate=0.09 / exception_rate=0.00`），与任何单张卡的方法行为无关。 | `search_records(kind=self_eval, query="SE-20260923-001-dce6")`；`evidence_refs` 频次统计 |
| S3 | **零独立评估者**：73/73 条 `evaluator="model"`。晋升证据链上不存在第二个判断主体。 | 字段统计 |
| S4 | **激活门卡死而非泄漏**：EVO-20261010-994e30f4 要求 `verdict=pass` 条目覆盖 ≥2 个不同 `task_type`。73 条中仅 1 条带 `task_type` 键且值为 `unknown`。唯一一条 lifecycle 尝试（2026-10-12T23:34:34）被 block，`detail="distinct pass task_type count=0 (<2)"`。**新卡当前无法激活，与证据质量无关。** | `data/methods/lifecycle_attempts.jsonl`；`store.py:1263-1288` |
| S5 | **无事故**：usage 20 事件 / 16 episode，applied 16、adapted 3、not_applicable 1、**rejected 0**、零事故记录。 | `data/methods/usage.jsonl` |
| S6 | **独立性守卫确实在工作**（对照组，说明并非全盘失效）：68 张有 qualification 的卡中，只有 1 张的 qualification episode 等于其 source episode。`store.py:1069-1075` 的两条硬约束生效。 | 交叉比对 |

### 1.3 根因

晋升门缺的不是**验证深度**，是**证据相关性**。当前 `promotion` 轴与 `verdict` 轴**程序上完全解耦**：`store.py` 只在写 qualification 时校验 `promotion=pass` 的 episode 独立性，**从不校验 `promotion=pass` 是否伴随一个已评估的 verdict**，也**从不校验 evidence 是否指向本卡专属事实**。于是「用一条全局窗口指标，为 59 张卡同时签发晋升声明」在契约上是合法的。

这与 held-out 缺失是**不同的问题**。held-out 说的是「证据来自未参与生成的样本」；S1/S2 说的是「证据与被判断对象无关」。后者更靠前，且**不需要重放即可判定**。

### 1.4 量化现状（实测）

- `data/methods/` 892 张卡：**859 candidate / 28 hold / 2 active / 1 qualified / 2 retired**。
- qualification 条目 73 条，分布在 68 张卡上。
- 按 (promotion, verdict) 交叉：

  | promotion | verdict | 条数 |
  |---|---|---|
  | pass | **not_evaluated** | **53** |
  | pass | pass | 7 |
  | not_evaluated | pass | 4 |
  | fail | not_evaluated | 9 |

- 53 条违规条目分布：51 张 candidate、2 张 hold —— **零张 active/qualified**。
- 收紧后仍可作为晋升证据存活的条目：**7 条，分布在 5 张卡**（`fresh-read-authoritative-record-before-finality-claim`、`resume-continuation-via-named-provenance-and-git-delta`、`self-execute-review-contract-on-degenerate-tool-output`、`lfl-mirror-qualified-worktree`、`locate-project-env-before-symptom-workarounds`）。

---

## 2. 现状事实（设计依据，均已核验）

| 事实 | 证据 |
|---|---|
| `store.py` 对 `promotion=pass` 只做两条校验：不得等于 source episode；必须带 `episode:` 前缀 ref。**不校验 verdict，不校验 evidence。** | `src/llm_loop/methods/store.py:1063-1075` |
| `qualified` 门：存在任一 `promotion=pass` 且带 episode provenance 的条目即可 | `store.py:1252-1262` |
| `active` 门：`verdict=pass` 条目的去重 `task_type`（去 `unknown`）≥2；存量 active 卡 grandfather 不回溯 | `store.py:1263-1288` |
| `evaluator` 是自由字符串，默认 `"model"`，程序不校验取值 | `store.py:1057,1090` |
| `evidence_refs` 是自由字符串数组，程序不校验格式、不校验指向、不查重 | `store.py:1088` |
| 同一 episode 内 `record_use` 与 qualification 重叠：5 张同时有两者的卡中 2 张重叠 | usage/qualification episode 交叉 |
| `docs/governance/card-lifecycle.md` 附录 D 硬边界明写：**不改运行时代码与工具 Schema；纯流程/文档/提醒层** | 附录 D |
| 本仓 2026-10-06 刚以「痛点证据不足，retire 比再烧一轮更诚实」retire 了 subject-binding 线，依据 n=9 全正、零事故、零可量化损失；其 reopen 前置条件为「先有遥测，再有新 holdout」 | `evals/method_binding_efficacy_v3/PRODUCTION-VALUE-AUDIT.md` |
| card-lifecycle R3 三轴中「门禁轴」明确只走 promotion 流程，不构成失效理由 | `docs/governance/card-lifecycle.md` R3 |

---

## 3. 需求

### R1（主阀门）promotion 与 verdict 耦合

程序拒绝 `promotion=pass` 与 `verdict ∈ {not_evaluated, insufficient}` 共存。判据是**同一条记录内的字段一致性**，不是语义判断，不涉及重放。

- 管 S1。0 provider 成本，机械可判。
- **不追溯**存量（附录 D），但存量违规条目按 §5.3 只作「不计入晋升证据」的历史保留。

### R2（主阀门）晋升证据的卡片级归属

`promotion=pass` 的条目必须携带**至少一条本卡专属 evidence ref**，且程序拒绝把**同一 ref 同时用作多张不同卡的 promotion=pass 唯一证据**。

- 管 S2。59 卡共用一条全局窗口指标是**相关性伪影**：59 次「独立」晋升判断，实为对同一条聚合指标读 59 次，n=59 的假象自由度。
- 判据可机械执行：ref 集合在卡之间的独占性统计。

### R3（② 保留但重定标）promote-to-active 的跨能力回归检查

新增卡进入 active 前，必须对**当前 active 集**做一次回归检查并留下机械证据。

- **成本重定标**：active 集是 **2 张卡**，不是 892 张。检查面 = 2 次比对，不是 859 卡重放。
- 这是原提案 ② 中**唯一值得立刻做**的部分，因为它的成本与其收益同量级。
- 形式：流程义务 + 产物留痕（附录 D 允许层），检查项固定为：新卡 Trigger 与既有 2 张 active 卡的 Discriminator 是否冲突；新卡 Short path 是否覆盖既有卡已覆盖的动作；结论必须带机械证据（检索 ref / 摘录）。

### R4（明确不做，带 reopen 条件）held-out 重放门

**本设计不建 held-out 重放基础设施。** 理由与 reopen 条件见 §4 M2/M3。

reopen 必须**同时**满足：

1. R1/R2/R3 已落地并产生真实 qualification 流量（当前 n=73，且 0 条独立 evaluator）；
2. 生产出现 **≥3 起**「已晋升卡导致可量化损失」的事故记录（当前 = 0，usage 20 事件零 rejected）；
3. 遥测先行：`record_use` 决策流可按自然 closeout 回路统计（当前 20 事件 / 16 episode，negative 决策 0，无法估计效应量）；
4. 一次预注册、带 stop rule 的新 holdout（沿用 `confirmatory_holdout_v1/PREREG.md` 的盲双评 + κ + anti-leak + sealed 形态）。

条件 1-3 全部指向同一件事：**先有可测量的痛，再有昂贵验证**。这与 PRODUCTION-VALUE-AUDIT 是同一条纪律，不是新发明。

### R5 边界变更请求（本文只提请，不越界执行）

R1/R2 必须改 `store.py` 的写入校验，**与附录 D「不改运行时代码」直接冲突**。本文的处理：

- 本设计**不执行**任何代码变更；
- R5 = 向 owner 提交一条 EVO，请求把附录 D 的边界从「纯流程/文档/提醒层」扩为「知识资产资格门可含写入期机械一致性校验（不得含语义判断）」；
- EVO 未批准前，R1/R2 只能以**流程检查清单**形式存在（`qualification` 写后自检 + 审计抽检），效果弱于程序硬承载，且必须在 §5.4 如实登记这一降级。

---

## 4. 拷问记录与设计修正

> **过程声明（诚实）**：`grill_me` 第 1 层返回的是**通用盘问单**（空输入 / 时钟网络磁盘 / 并发 / 权限缺失 / 版本不一致 / 数据丢失 / 失败检测 / 重试退避 / 敏感数据 / 滥用入口），并非针对本设计的定制问题。其价值在于强制逐条作答；下表左列为通用问题向本域的映射，右列为作答导致的**真实设计变更**。未采纳花架子，未虚构工具产出，也未假装 grill_me 问出了我没问过的问题。

| # | 拷问点 | 作答 ⇒ 设计变更 |
|---|---|---|
| M1 | 最坏失败场景（数据丢失/损坏） | 重放门最坏不是丢数据，是**误拒真实好卡**：把 892 张候选卡挡在门外、诱导模型改写卡片去迎合门。**变更：删除 held-out replay 门**（原 D1），改为写入期字段一致性（R1）+ 证据独占性（R2），二者不会把「好卡」和「坏卡」一起拒掉——它们拒的是**自相矛盾的记录**与**伪独立证据**，好卡补一条真 verdict 即可通过 |
| M2 | 失败如何检测 / 重试策略 | 重放门的失败**不可检测**：n=73、evaluator 全 model、零事故 ⇒ 无法区分「门挡住了坏卡」与「门什么都没挡」。**变更：R4 明确不建重放门，改为带回open条件的延后项**；并把「可检测性」写成 reopen 条件 2-3（须先有 ≥3 起可量化事故 + 遥测），而不是先建门再指望它可检测 |
| M3 | 与本仓既有裁决是否自相矛盾 | PRODUCTION-VALUE-AUDIT（2026-10-06）刚以「痛点证据不足，retire 比再烧一轮更诚实」retire 一条线，依据 n=9 全正零事故。当前 method 证据形态**同构**（n=20 全正、零 rejected、零事故）。**变更：这是推翻用户加强论证的决定性一条。** held-out 重放会**扩大暴露面**（支撑更多晋升），而扩大暴露的前提是已有痛；本仓已就同类形态做过相反裁决。故 R4 延后 |
| M4 | 空输入 / 无 verdict 的 qualification | 原提案默认「每条 qualification 都有可重放的 verdict」。实测 **53/73 是 not_evaluated**。**变更：R1 写成契约级耦合约束**——这才是真正的缺口，且无需重放即可判 |
| M5 | 并发 / 幂等 | 晋升是 RMW（`_store_lock` + 原子替换），R1/R2 校验放在 `_record_qualification_locked` 内，与既有两道校验同位置 ⇒ 天然同锁同事务。**变更：R1/R2 明确要求写入期校验，禁止事后批量修**（事后修 = 改历史 = 违反附录 D） |
| M6 | 权限缺失 / 谁判定「证据够」 | 程序只能判**字段一致性**与**ref 独占性**，不能判「这条证据是否真的证明了收益」。**变更：R3 的回归结论必须带机械证据但由模型裁决**，程序只校验证据存在性——与既有 `_disposition_basis()` 的分工一致（程序报事实，不下语义判决） |
| M7 | 规模（数据量 ×1000） | 重放 892 卡 vs 回归 2 张 active 卡，成本差 **446×**。**变更：重排优先级 R1/R2/R3 全部先做，R4 延后**；并把 ② 明确重定标为「成本 2 张卡的检查」，而不是用户原提案隐含的「对晋升做重放」 |
| M8 | 版本不一致 / stale 证据 | S2 里的 `eval:SE-...` 是**一次性窗口聚合**，天然随时间失效但永不被发现。**变更：R2 的独占性检查顺带暴露 stale**——若某 ref 只支撑一张卡，它仍可能 stale，故 R2 不宣称解决时效性；时效性归 card-lifecycle R4 周检，不在此设计内 |
| M9 | 敏感数据 / 权限边界 | R2 只统计 ref 字符串在卡之间的复用，**不解析 ref 内容**，不新增读权限面。**变更：R2 明确限定为集合运算，禁止把 ref 解析成路径后读文件**（否则从 qualification 校验开出任意文件读权限） |
| M10 | 可被滥用的入口 | 一个「凑够证据就能晋升」的门会诱发证据注水。**变更：R1/R2 只做减法式校验（拒矛盾、拒伪独立），不提供任何「加什么就能过」的快捷路径**；且 R3 要求回归证据，不接受自述 |
| M11 | 部分错误 / 存量 53 条怎么办 | 附录 D 禁回填、禁物理删除。**变更：§5.3 定为「标记不计入、不删除、不回填」**；并核验收紧后当前 2 张 active + 1 张 qualified **不倒**（已核：其 `promotion=pass` 条目均 `verdict=pass`） |
| M12 | 自身文档会不会腐烂 | 引用全部用 stable id / 字段名，不用行号以外的易腐物；§7 验收清单给出机械重跑命令 |

---

## 5. 设计补充

### 5.1 R1 契约（写入期机械一致性）

```
record_qualification(method_ref, task_ref, verdict, promotion, evidence_refs, ...):
    # 既有两条校验，保持不变
    if promotion == "pass" and task_ref in record.source_episode_refs: reject
    if promotion == "pass" and not task_ref.startswith("episode:"):  reject
    # 新增 R1
    if promotion == "pass" and verdict in {"not_evaluated", "insufficient"}: reject
        missing_fact = "coupled_promotion_verdict"
    # 新增 R2
    if promotion == "pass" and not card_scoped_evidence(evidence_refs, method_ref): reject
        missing_fact = "card_scoped_evidence"
    if promotion == "pass" and ref_is_promotion_sole_evidence_for_others(ref, method_ref): reject
        missing_fact = "non_independent_evidence"
```

三条都是**字段/集合级**判据，不读 ref 指向的内容（M9）。

### 5.2 R2 的「本卡专属」判据

程序可机械判的最小版本（不做语义理解）：

- 集合运算：统计每个 `evidence://`/`eval:`/`episode:`/`file:`/`method:` 前缀 ref 在**多少张不同卡**的 `promotion=pass` 条目中出现；
- 若某 ref 是 N 张卡（N ≥ 2）的 promotion 证据，则它对任何单卡都**不构成专属证据**；
- 卡自身专属的可接受形态：`episode:`-scoped（本次或既往 episode）、`file:`-scoped 指向本卡产物、`method:<self>`、`evidence://` 快照。`eval:SE-*` 窗口聚合**不计入**。

这是「去相关」而非「证真」：它只保证**证据不与 59 张卡共享**，不保证证据正确。正确性仍归 card-lifecycle R4 周检。

### 5.3 存量 53 条的处置

- **不回填**（附录 D）；
- **不删除**（卡片永不物理删除）；
- **不追溯**为资格事故（门禁轴 ≠ 失效轴，card-lifecycle R3 明文）；
- 程序侧仅登记「不计入 promotion 证据」，使 `qualified`/`active` 判定**在存量卡上语义不变**；
- 唯一建议动作：周检抽到这些卡时，按 R1 补一条**真实的** qualification（真实 episode + 真实 verdict），而不是改写旧条目。

### 5.4 边界降级（如实登记）

若 R5（EVO）未获批，R1/R2 无法进入写入期校验，降级为：

- 流程层：`docs/governance/card-lifecycle.md` 增一条写后自检；
- 审计层：周检抽检 qualification 新条目，发现 `promotion=pass + verdict=not_evaluated` 即登记。

**如实声明**：该降级形态**拦不住**批量写入，只能事后发现。它是本设计在未获 EVO 时的真实能力上限，不得宣称「已建立晋升质量门」。

### 5.5 度量

| 指标 | 定义 | 健康线 | 异常含义 |
|---|---|---|---|
| M-耦合 | `promotion=pass ∧ verdict∈{not_evaluated,insufficient}` 条目占比 | 新条目 = 0 | >0 ⇒ R1 未生效或被绕过 |
| M-独立 | promotion 证据 ref 的「跨卡复用」最大扇出 | = 1 | >1 ⇒ R2 未生效；S2 类伪独立仍在发生 |
| M-评估者 | `evaluator != "model"` 的条目占比 | 上升中 | 长期 = 0 ⇒ 晋升仍无第二判断主体 |
| M-死门 | 90 天内 successful activate 次数 vs blocked 次数 | blocked 有下降 | 持续全 block ⇒ 激活门仍是死的（S4），需单独处理 |

M-死门刻意保留：本文修的是**证据诚实**，不修**激活门可满足性**。后者（task_type 无数据）是独立问题，须单独裁决，不得混入本文冒充已解决。

---

## 6. 实现方案（**全部 NOT RUN**）

| 步 | 动作 | 产物 | 前置 | 状态 |
|---|---|---|---|---|
| I0 | 提交 R5 边界变更 EVO（附录 D 扩边界） | EVO 建议 | owner 授权 | **NOT RUN** |
| I1 | `store.py::_record_qualification_locked` 加 R1 校验 + `_blocked(missing_fact="coupled_promotion_verdict")` | 代码 | I0 批准 | **NOT RUN** |
| I2 | 同处加 R2 校验（集合运算，不解析 ref 内容） | 代码 | I0 批准 | **NOT RUN** |
| I3 | 单测：R1 拒绝矛盾组合；R2 拒绝跨卡复用 ref；存量 2 active/1 qualified 仍可 activate（grandfather 语义不回退） | `tests/unit/test_method_store_durability.py` 等 | I1,I2 | **NOT RUN** |
| I4 | R3 回归检查清单（对 active 集，n=2）写入 card-lifecycle | 文档 | 无 | **NOT RUN** |
| I5 | 度量 §5.5 四项接入周检产物 | 文档/脚本 | I4 | **NOT RUN** |
| I6 | R4 保持不做，仅在本文登记 reopen 条件 | 本文档 | — | **N/A（明确不做）** |

---

## 7. 验收清单

1. `grep -c '"promotion": "pass"' data/methods/*/qualification.jsonl` 与 verdict 交叉统计：存量 53 条被标记不计入；新增条目违反率为 0。
2. 2 张 active + 1 张 qualified 的 lifecycle 判定**不变**（须重跑 dry-run 并对比）。
3. M-独立扇出 = 1（`eval:SE-20260923-001-dce6` 不再作为 59 张卡的 promotion 证据）。
4. 若 I0 未获批：§5.4 降级声明已在 card-lifecycle 中登记，且**不得**出现「已建立晋升质量门」类表述。

---

## 8. 边界与非目标

**非目标**：不判定单张卡内容对错；不改 R3 三轴失效流程；不改检索融合参数；不解决 S4 激活门可满足性；不新增任何 provider 调用；不引入 replay harness。

**明确不改**：`evidence_refs` 的自由文本格式（避免 schema 破坏）；`evaluator` 字段语义（本期只度量，不加校验）。

**越界声明**：本文未执行任何 I0-I6 中标记 NOT RUN 的动作，未修改 `store.py`，未修改任何 `qualification.jsonl`，未触碰任何卡片状态。

---

## 9. 开放问题

1. **S4 激活门卡死**（task_type 无数据 ⇒ 新卡恒不可激活）是独立且更紧迫的问题：它意味着当前晋升流程**根本没有在运行**。本文刻意不修。是否立即另起一轮裁决？
2. `evaluator != "model"` 目前恒为 0。要不要把「独立评估者」写成 R1 的第二阶段（会进一步降低晋升率）？
3. 若 R1/R2 落地后 53 条候选卡仍大批滞留 candidate（859 张），M-阀门（失效:新建）会失衡。是否需要单独的收敛节奏？
