# DESIGN-20261006 能力生态与生命周期漏斗 — 需求设计

Date: 2026-10-06
Status: **DRAFT — 需求设计，待用户裁决采纳；本文不含实现**
上游: 2026-10-06 生态对比分析（Claude Mods / DSH Plugins / LFL 定位）

## 0. 证据基线（全部本会话实测或仓库已核文档）

| 事实 | 数值 | 来源 |
|---|---|---|
| 方法池快照 2026-10-06 | total 626 = candidate 593 / hold 28 / qualified 1 / active 2 / retired 2；with_qualification 67；with_usage 5（applied 5） | architecture_status knowledge_health 实测 |
| freshness 覆盖 | not_tracked 622 / current 2 / unbaselined 2 | 同上 |
| 语义开关实测 | semantic_memory=**true**；semantic_method / experience / docs = false；embedding=api/bge | architecture_config 实测 |
| 检索污染（重放 71 条真实 query） | 70/71 top-5 含 candidate；38/71 高价值卡被挤出；高频干扰集中 25 张；dead-but-harmless 384 | ASSESS-20260929-method-pool-census.md |
| 高频 25 张分诊结论 | 12 张建议 qualification、9 张暂不动、2 张同族、1 张 stale（record-use-v3） | ASSESS-20260929-p5a-highfreq-triage.md |
| Learning Method semantic | isolated qualification **PASS**，生产激活 NOT YET AUTHORIZED；§Production boundary 已备 8 步 runbook | PLAN-20260926-learning-method-semantic-integration.md |
| DSH 插件互操作层 | tools_skill_dsh.py（140 行）：白名单仅 raw.githubusercontent.com、TTL 86400s、只读、执行归 DSH CLI | 源码实测 |
| dsh_task 预检现状 | 466 行中无 plugin 逻辑，仅 dsh 可执行存在性检查（:181） | 源码 grep 实测 |
| 其他资产 | skills 24 / experiences 323 / rules 26 / evolution 165（executed 98） | 本会话实测 |

数字漂移声明: census（09-29）n=555（hold 1）→ 今日 16:3x 626（hold 28）→ 17:1x 锚定 639（增量全 candidate）。hold 增量成因已核验：09-30 15:30 单批 27 张 candidate→hold（见 §7 Q1 与 ASSESS-20261006-q1-hold-growth-census.md）。本文一律以快照日期双标，不用单一数字。

## 1. 背景、定位与问题诊断

外部动向：Claude Mods（终端可定制）与 DSH（一切皆插件 + Mods 兼容层）都在抢占**跨工具复用**。LFL 的生态位不是第三个插件框架，而是**能力生命周期管理**：发现 → 蒸馏 → qualification → 激活 → 使用 → freshness 跟踪 → 退休。外部插件清单是静态的；LFL 方法池是带资质与时效的活资产——漏斗质量即壁垒。

数据诊断（按证据基线）:

1. **供给侧强、消费侧弱（主病灶）**: 626 张方法卡，with_usage 仅 5、qualified 仅 1。census 结论同判："qualification 与 use 回流几乎没发生，这是主要病灶，不是卡片数量本身"。
2. **检索污染定向、非全局**: 38/71 真实 query 被高频 candidate 挤出高价值卡，但干扰集中在 25 张且 active +35 生命周期权重已保障召回优先级 → 修漏斗与处置清单，不必重建检索引擎。
3. **语义检索非空白**: Learning 侧 consumer 已接线，isolated qualification PASS（7/7 rank#1；A/B：OFF 0/3 识别重复 vs ON 3/3；159/159 回归 PASS）。卡点只剩**生产激活授权**，不是要不要做实验。
4. **外部桥接单向断头**: 索引可查、插件卡可读，但 dsh_task 无插件可用性预检，缺失场景静默失败；LFL 无对外交换单元。

## 2. 目标 / 非目标

**目标（12 周观察窗）**

- G1 Method 漏斗消费侧打通：qualified ≥ 3、with_usage ≥ 12。
- G2 生产激活 Learning Method semantic：单变量、零事故、可回滚。
- G3 DSH 桥接闭环：委派前可预检、失败可归因、缺失如实可见。
- G4 Method→Skill→Experience 资产循环最小闭环 ≥ 1 个端到端实例。

**非目标**

- 不做通用插件执行框架（红线，见 NFR-1）。
- 不批量刷 qualification（P5-A 明确：只认真实任务命中时的逐张补充）。
- 不动 384 张 dead-but-harmless（census P5-D：处置无收益且有误杀风险）。
- 不扩 semantic_experience / semantic_docs（单变量原则，留观察期 Q4）。
- 不自动对外发布任何资产（P2 仅人工评估路径）。

## 3. 需求分解

### FR-1（P0）Learning Method semantic 生产激活

- 需求：按 PLAN-20260926 §Production boundary 步骤 1–8 执行：干净候选经 managed authority 发布 → 仅 Learning 侧 Method override（Archive/Docs/Experience 保持 OFF）→ dry-run 校验 → Learning idle gate 后单服务重启 → manifest 验证 → smoke 重跑 → Web/Feishu 不受扰 → 触发 stop condition 即回滚 override。
- 授权性质：owner checkpoint（用户裁决），配置覆盖而非代码变更，不走 submit_evolution。
- 验收：Learning manifest Method=1 / 其余=0 且 provenance 正确；canonical Method tool/model smoke 通过；Web/Feishu PID/健康不变；embedding 错误 0、队列 idle；回滚演练一次成功。

### FR-2（P0）qualification 漏斗消化（承接 P5-A 清单）

- 需求：12 张增量候选逐张 qualification（**仅真实任务命中时补，不批量刷**，每张独立于蒸馏会话）；#3 record-use-v3 积累独立证据后 invalidate 或重写对齐 v2.2；#19/#24 同族二选一保留（处置需独立依据）。
- 验收：qualified ≥ 3（含存量 1）；高频 25 张中 ≥ 10 张获得终态；每张 qualification 证据可回溯（task_benefit 实证口径）。
- 节奏说明：依赖真实任务命中，属慢变量，与 FR-1/FR-4 并行推进。

### FR-3（P0）消费侧观测

- 需求：激活后 Reflection 的 method_discovery 命中/采纳计数持续落盘（沿用顶层 usage.jsonl 口径，P4 扫描 bug 已修正）；指标可机械重放。
- 验收：with_usage 自 5 起的增长曲线可按月读取；命中/采纳/拒绝比例可见。
- 防好球带（goodhart）：行为计数仅观测，不作为自动晋升输入。

### FR-4（P1）dsh_task 插件可用性预检

- 现状：dsh_task.py 无任何 plugin 逻辑（仅 dsh 可执行检查）。
- 需求：委派含插件语义的任务前，经 **DSH 侧 CLI 只读查询**已装清单（形态待实测，Q2）；未安装 → 如实返回"需人工 `dsh plugin add`"，不自动安装、不重试。
- 红线：不执行插件代码；查询走 DSH CLI 自身，**不新增 LFL 白名单域**。
- 验收：缺插件场景 100% 预检可见（不再静默失败后才归因）；非插件任务零额外开销；查询失败 fail-open 降级为现行为并如实标注。

### FR-5（P1）Method→Skill 晋升管线

- 现状：24 个 skills 中 12 个已是 method-* 命名——通路事实上存在，但无规范、无 freshness 继承、无回流。
- 需求：active/qualified 方法经 record_skill 蒸馏为 SKILL.md 的流程规范（晋升时机、命名、与既有 skill 去重、freshness_refs 继承）；skill 使用经验按现行机制回流 experience。
- 验收：规范落 docs/；≥ 1 张 qualified 方法完成端到端晋升实例（含去重检查记录）。
- 依赖：FR-2 首批合格卡。

### FR-6（P1）插件-任务匹配主动提示

- 现状：skill_list 尾段已展示索引（被动）；插件卡可查。
- 需求：任务描述与插件 desc 相似时输出 advisory 提示"可能有适用的 DSH 插件"。关键词匹配起步即满足；语义匹配可复用 FR-1 的 embedding 通道但非必需。
- 红线：只提示不执行；提示可关闭；失败 fail-open。
- 验收：提示触发/采纳记录落盘可观测；误报率有观察记录；载体选择见 Q3。

### FR-7（P2）非代码 DSH 插件只读导入

- 需求：prompt/方法论/文档类插件卡 → 本地 skill **草稿**（人工确认后生效），保留 `dsh:` 前缀溯源，可一键删除。
- 门槛：导入前确认内容纯文本、无代码执行语义；任何存疑即拒绝。
- 验收：导入项带 provenance；删除后无残留。

### FR-8（P2）LFL skills 对外输出

- 需求：审计 LFL SKILL.md 子集与外部清单格式的兼容性，形成可贡献清单；回馈 awesome-dsh-plugin 走人工 PR。
- 验收：兼容性审计结论 + 候选清单产出（不自动发布）。

## 4. 非功能需求

- **NFR-1 安全红线不变**：白名单域仅 raw.githubusercontent.com（任何扩展走 submit_evolution 人工审批）；LFL 不下载、不执行插件代码；安装归 DSH 官方 CLI。
- **NFR-2 一切 advisory**：检索、提示、推荐均不自动执行、不自动晋升、不自动安装。
- **NFR-3 单变量 + 可回滚**：语义激活只动 Learning override；每步带 stop condition 与回滚面。
- **NFR-4 fail-open**：索引/预检/提示失败不阻塞主流程，且必须如实标注而非静默降级。
- **NFR-5 观测落盘**：qualified / with_usage / 命中采纳 / 预检命中率等关键指标机械可重放。

## 5. 里程碑与依赖

| 里程碑 | 内容 | 依赖 |
|---|---|---|
| M1（第 1–2 周） | FR-1 激活（1 个部署窗口）+ FR-3 观测上线 | 用户授权 |
| M2（第 2–8 周） | FR-2 漏斗消化（慢变量）；FR-4 预检（独立小改动，可提前） | FR-2 依赖真实任务；FR-4 依赖 Q2 实测 |
| M3（第 4–8 周） | FR-5 晋升管线；FR-6 提示 | FR-5 依赖 FR-2 首批合格卡 |
| M4（第 8–12 周） | FR-7 / FR-8（人工评估门） | FR-1–FR-6 结论 |

## 6. 风险

- R1 激活回归 → 8 步 runbook + 单服务回滚演练。
- R2 生成快于消化 → method_reflection=auto 生成端暂不扩产；若 12 周后 candidate 净增仍 > 2× qualified，评估上调 min_rounds/min_failures 阈值。
- R3 DSH CLI 插件查询形态不稳 → 查询失败 fail-open 降级为现行为。
- R4 好球带（凑 with_usage 刷使用）→ 严格 usage.jsonl 认定；采纳计数不联动晋升。
- R5 hold 28 张构成未明 → Q1 增补 census，不阻塞本设计。

## 7. 开放问题

- Q1 hold 28 的成因与处置路径 → **已核验闭环（2026-10-06，ASSESS-20261006-q1-hold-growth-census.md）**：2026-09-30 15:30 单批 27 张 candidate→hold（472c1163c 补收的旧运行时卡，f1746f41a 落盘）；非逐日积累、非口径变化，hold 不进语义权威集，对 FR-1 零影响；决策 rationale 未在仓内留痕（如实声明）。
- Q2 DSH CLI 插件查询子命令的实际形态（FR-4 前实测）。
- Q3 FR-6 载体：前台检索层 vs skill_list 增强（成本/收益权衡）。
- Q4 语义激活稳定后是否扩 semantic_experience（本设计明确不扩，观察期后复议）。

## 8. 对前轮对话分析的修正（诚实记录）

1. "semantic_* 全 false" → 实测 semantic_memory=**true**（method/experience/docs 为 false）。
2. "P0 需做 semantic qualification 实验" → PLAN-20260926 已 isolated PASS，剩余动作是**生产激活授权**，非新实验。
3. "625 方法 / 592 candidate" → 今日 626 / 593（快照日期不同）。
4. 未提 hold 变化 → census 后 1 → 28，成因已核验（见 §7 Q1），已列 Q1。

## 9. 裁决采纳与隔离声明（2026-10-06 追加）

5. **裁决采纳**：用户转达外部裁决——FR-1 激活准备为主线、停在 owner authorization checkpoint（不直接执行生产激活）；Q1 并行只读（已闭环）；Q2 后置到 FR-4 开工前。授权包已备：`PLAN-20261006-fr1-semantic-method-activation-authz.md`（READY，含 G1–G5 currentness gate，待 owner 授权）。
6. **隔离声明**：FR-1 依据的 Learning Method semantic qualification（PLAN-20260926）与 Method Subject-Binding v3（EFFICACY_NOT_QUALIFIED，a33f6312 冻结、line retired）是两个不同裁决面，**证据互不借贷**——前者进入激活准备不推翻后者 no-promotion 结论，后者也不得引用前者 PASS 为 v4 复活背书。
7. **权威集缩小说实**：qualification（09-26）时语义权威集为 7 active 家族，当前为 active 2 + qualified 1 = 3 张。FR-1 canary 目标集须按执行时权威集重新 derive（授权包 G2），不得照搬 7/7 历史口径。

## 10. FR-1 执行后状态（2026-10-06）

- FR-1 已按授权包完成生产激活并进入 **ACTIVATED / OBSERVING**：generation 181、Learning-only Method semantic=1、3/3 canary rank#1 + semantic_effective + 零 fallback，Web/Feishu 无扰动，零 stop condition。权威执行证据见 `PLAN-20261006-fr1-semantic-method-activation-authz.md` §10–§12。
- 生命周期未在 T+0 直接标 COMPLETE：须继续 T+24h / T+7d / T+28d 观测；其中 T+24h 关闭“激活安全性”层，后续窗口验证持续稳定性与消费侧效果。
- T+24h 前原计划保持 `src/` 冻结；只读 lint 复核发现 `BindingPolicy` 字段/classmethod 同名导致直接默认构造 `BindingPolicy()` 在 real verdict 上真实 fail-open。后续 owner 明示“继续修复”，仅对该 F811 正确性缺陷覆盖源码冻结：classmethod 改名为 `permit_real()`、补默认构造 fail-closed 回归并通过邻接验证；**未 publish/restart**，故 Learning gen181 的生产运行时单变量观测仍保持不变。详见授权包 §12–§12.1。
