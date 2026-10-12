# POSTMORTEM-20261006 — Method Subject-Binding 研究线（v1–v3）复盘与 v4 前景

性质：**post-hoc 探索性复盘**，用户显式授权（2026-10-06 选项 C）。
不重开、不修改任何冻结裁决；所有 post-hoc 分析仅作研究归因与 v4 前景论证。
冻结结论见 `docs/RESULT-20261006-method-binding-v3.md`（FINAL）。

---

## 1. 一页结论

- 研究假设：给 `save_experience` 工具描述附加 subject-binding 提示，能让模型在自然
  closeout 中正确**拒绝**把 Method/经验套用到 subject 不匹配的当前任务上。
- 终局：v3 确证 **EFFICACY_NOT_QUALIFIED**（strong net=2、weak net=2，均低于预冻结
  net≥3 且 −≤1），方向双模型一致为正，但幅度不足。**Line retired，无生产变更。**
- 三代死因各不相同，且逐代被修复：v1 **仪器无效**（结构上限 +1 例 vs 需要 +6 例）→
  v2 **机会为零**（13/13 任务文本自带易 SKIP 通道，C0 零错误）→ v3 **仪器与机会均
  有效，但机制转换率不足**（cue 只能转化 25–40% 的 C0 错误，strong 还引入 2 例反向伤害）。
- 生产侧：7,864 次检索中可观测的使用决策仅 9 例、mis-binding 事故 0 例——**生产痛点
  证据不足**，任何 v4 PASS 都无法与生产价值挂钩（除非先补遥测）。
- v4 前景判断：**不建议以现有机制直接重开**。cue-only 机制在有效仪器上的实测净效应
  ≈ 0.118（2/17），低于预冻结门槛 0.1765（3/17）；这不是 n 不够，是机制饱和。
  v4 若重开必须同时满足三条前置（§7）并换更强机制。

## 2. 时间线与死因链（全部有冻结工件佐证）

| 代 | 设计 | 规模 | 结果 | 死因（事后归因） |
|---|---|---|---|---|
| v1 (10-05) | 显式判别 2×2，M1=+0.15 | 40/arm | FAIL（Δ+0.025；verdict GUARDRAIL BREACH） | **仪器无效**：池结构上限 +1 例、噪声地板 0.30>0.15、6/7 C1 错案是同域孪生标签噪声；唯一 purpose 级分歧案 mb-024 被 binding 修复 |
| v2 run2 (10-06) | 新池+金集，同显式判别 | 84 cells | EFFICACY_NOT_QUALIFIED（护栏全过） | **机会为零**：B 层 13/13 任务文本含显式否定/替代路径 → Strong/Weak C0 均 0/13 错误，无 headroom 可赢 |
| v3 dev (10-06) | 自然 closeout 协议 C0-only | 44/44 | PASS（负向准确率错误 0.727，集中在 3 个 family） | —（校准成功：难度带 0.45–0.80，same_infra family 因天花板 1.0 淘汰） |
| v3 holdout (10-06) | 全新池，双盲标签资格 | 23 例 | PASS（R1/R2 agreement=1.0，κ=1.0，anti-leak=0） | — |
| v3 confirm (10-06) | 92-cell 配对矩阵，双模型 | 92/92 attempt0 | **EFFICACY_NOT_QUALIFIED** | **转换率不足**（§4）：机会如期出现，cue 转化不了 |
| 生产审计 (10-06) | provider-free | — | 痛点 INSUFFICIENT | 遥测缺口：9/7864 可观测，0 事故 |

Provider 消耗合计（近似，源工件）：v1 80 scored + 80 technical rerun、v2 run2 84、
v3 dev 44 + preflight 4 + confirm 92 ≈ **384 cells**。三代机械健康全绿，无一例
reserved/重放/attempt0 之外的路径。

## 3. v3 终局数字（冻结，RESULT.json）

| model | challenge C0→C1 | +flip | −flip | net | 阈值 | reverse-risk | token比 |
|---|---|---|---|---|---|---|---|
| strong (deepseek-v4-flash) | 7/17 → 9/17 | 4 | 2 | 2 | net≥3 且 −≤1：双项未达 | 4/6→6/6（0 harm） | 1.0205 |
| weak (qwen3.8-flash-next) | 9/17 → 11/17 | 2 | 0 | 2 | net≥3：差 1 | 6/6→6/6（0 harm） | 1.0448 |

护栏（safety/cost/reverse-risk）双模型全 PASS；92/92 全 attempt0、mechanically_healthy、
模型身份精确、binding 断言与臂一致。

## 4. 近失解剖（本文新产出，post-hoc）

数据：`confirmatory_provider_v1/matrix.jsonl` 92 行 latest 集合，配对翻转逐案归类。

**4.1 机会如期兑现，转换率才是短板。**
dev 校准预测 C0 错误带 0.45–0.80；实测 strong C0 错 10/17=0.588、weak 8/17=0.471，
均落在带内——v2 式"机会为零"已被修复。但 cue 只转化了其中一部分：
- strong：转化 4/10（40%）C0 错误，同时引入 2 例新错（均为 C0 本来正确 SKIP、
  C1 被 cue 推向错误 APPLY）；
- weak：转化 2/8（25%），零新错；
- 双臂同错 floor：两模型各 6/17（35%）——cue 完全够不着的案群。

**4.2 反向伤害集中在 strong 的 same_workflow_different_phase。**
strong 的两个 −flip（B18、B15）都在该 family：C0 正确 not_applicable，C1 反而
applied/adapted。同 family 里 B14 又是 +flip。说明 cue 对 strong 在"同工作流不同
阶段"这一 family 上是**双向不稳定**的——它有时救（B14）有时害（B18/B15），
净效应在 family 内近似对消。weak 的 +flip（B09 evidence、B15 workflow）无此现象。

**4.3 基线悖论：strong 的自然 closeout 判别比 weak 差。**
C0 无 cue 时 strong 7/17 < weak 9/17。强模型在自然场景反而更倾向把 hydrated Method
套上去（更多 applied/adapted）。cue 的收益量与基线错误量正相关（strong +4 也
−2；weak +2 且 −0）——cue 是"纠错器"而非"能力增强器"，纠错上限受基线错误
结构限制，且对 strong 有副作用。

**4.4 未被设计预期的正收益：reverse-risk 被救活。**
strong reverse-risk 4/6→6/6（A06、A04 两例 C0 错误拒绝 → C1 正确 APPLY）。
cue 本为"防误套"设计，实际同时减少了"过度拒绝"。这个方向 v3 护栏有测但
主 gate 没押注；若 v4 重开，reverse-risk 修复是比 challenge SKIP 更干净的信号面。

**4.5 单翻转敏感性与判读边界。**
weak 距门槛恰差 1 个 +flip；strong 差 1 net 且超 1 个 −flip。n=17 下单个 case 的
决策噪声足以翻转结论——但预冻结规则就是预冻结规则，"差一点"不构成弱推广依据
（RESULT-20261006 §3 已裁决）。对 v4 的含义是：**要么机制把真实净效应抬到
0.20+ 留出噪声余量，要么先有生产遥测重新论证门槛本身**，而不是加大 n 赌阈值运气。

## 5. 机制层理解（三代累积）

1. cue 的作用通道是工具描述 + 模型自然推理，无结构性强制。它对"词汇同域但
   purpose 不同"的案（v1 mb-024、v3 evidence/object family）最有效；
2. 对"同工作流不同阶段"的案，subject 边界本身就模糊（阶段差异 vs subject 差异
   语义重叠），cue 依赖模型自由裁量 → strong 上双向不稳定；
3. 35% 双臂同错案群说明：存在 cue 文本完全无法触达的判别盲区（或标签边界的
   极限情形），这部分是机制的饱和上限；
4. 结论：**description-level cue 的真实净效应在有效仪器上 ≈ +0.12（±噪声）**。
   v4 若要过 0.1765 门槛，机制必须升级为决策时结构注入、检索时过滤或两段式
   裁定之一（或组合），而非更长的 cue 文本。

## 6. 方法论资产（line 留下的可复用能力）

这些不随研究线 retired 而失效，已沉淀在 repo：
- 预冻结 SPEC + FREEZE hash + 一次性 analyze（v1→v3 一贯）；
- 双盲标签资格（agreement/κ 报告）+ anti-leak 检查（holdout v1）；
- C0-only 机会校准协议（先测 headroom 再消耗 provider）——v2→v3 的关键转折；
- 配对翻转 gate（+flip/−flip/net）+ reverse-risk/安全/成本护栏；
- 机械健康检查（settlement/run.end/模型身份/attempt0 纪律 + reserved 恢复协议）；
- 生产价值审计模板（provider-free，痛点先于机制）。

## 7. v4 前景与 reopen 前置（retire 决定所列）

| 前置 | 状态 (2026-10-06 16:45) |
|---|---|
| ① 生产 record_use 遥测 | 修复已部署：commit `a519f41b9`，gen180（16:38 起）；+48h 自然观测 `sched-f486b1ad` 进行中；基线=全库 5 条声明 |
| ② 全新 fresh holdout + 新预冻结 SPEC | 未开始；须纳入本次实测难度带（机会带兑现但转换率 ~0.12）重新论证阈值可达性 |
| ③ operator 显式授权 | 未给出（本文档不构成授权） |

若三者齐备，v4 最小设计约束（据 §4–5）：
1. 机制升级（结构注入/检索过滤/两段式），预注册对比 cue-only 的增量；
2. 主 gate 至少押一个方向于 reverse-risk 修复面，或论证为何不做；
3. 门槛与生产遥测联动：若 48h+ 自然观测仍无 mis-binding 事件，v4 的存在理由
   需要从"修生产事故"改为"防患于能力扩张"（论证负担更高）；
4. family 层面剔除/降权 same_workflow_different_phase 的模糊案，或为其设计
   专门的判别辅助（v3 中它对 strong 是净零贡献）。

## 8. 明确不做的事

- 不放宽任何预冻结判据；不产出"差一点"弱推广；
- 不复用已消耗的 23 例 holdout；
- 不在遥测观测期内预启动 v4 池构造；
- remote push 维持不授权（本地 commit 遵循本线惯例）。

## 9. 权威工件索引

- 终局：`docs/RESULT-20261006-method-binding-v3.md` + `evals/method_binding_efficacy_v3/confirmatory_provider_v1/{RESULT.json,SYNTHESIS.md,matrix.jsonl,status/}`
- v1：`evals/method_binding_efficacy_v1/{RESULT.json,FORENSIC.md}`
- v2：`evals/method_binding_efficacy_v2/provider_matrix_v1/RESULT-RUN2.json`、`posthoc_opportunity_v1/OPPORTUNITY-FORENSIC.md`
- v3 dev/holdout：`evals/method_binding_efficacy_v3/{behavior_protocol_v2/RESULT.json,confirmatory_holdout_v1/LABEL-RESULT.json}`
- 生产审计：`evals/method_binding_efficacy_v3/PRODUCTION-VALUE-AUDIT.md`
- 遥测修复：commit `a519f41b9`（gen180）
