---
method_id: null-result-noise-floor-audit-before-mechanism-iteration-46498b4dded0
name: null-result-noise-floor-audit-before-mechanism-iteration
description: 当预注册的逐例配对评分实验以小效应 FAIL/近零 verdict 收场，而后续计划准备在多个机制改进分支（Method 质量/判别/行为转化/能力上限）之间选择或追加样本量时，先做 provider-free 仪器效度审计：只从冻结工件（pool 构造规则、每例标签 provenance、逐例双臂判决）计算 paired transition、信号层饱和度与标签噪声地板，并与预注册效应阈值做 headroom 算术。若可赢例数 < 阈值所需净翻转数，或噪声地板 ≥ 阈值量级，则任何真实机制在该仪器上结构性不可能通过，正确下一步是修仪器（独立双评分者重裁标签、构造 purpose 级近失陷阱），而不是迭代机制或加样本。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:abda90a9-c633-4664-b777-2ef993c8f7d9:375:e465304c8623d6faccae
evidence_refs: learning:learn:6f42cb6f0c09
created_at: 2026-10-06T01:23:35.777938+08:00
updated_at: 2026-10-06T01:23:35.777938+08:00
---
## Trigger
预注册评分实验刚产出小效应 FAIL 或近零 verdict，且下一步计划按机制分支分配资源（或考虑加样本重跑）；或即将在由机械规则（词汇/相似度重叠）生成 expected 标签的 case 池上投入 provider 预算之前。

## Discriminator
冻结综合与预注册当时已写明的事实组合：(1) 信号层饱和——如 match 层双臂全对，全部 Δ 只能来自唯一非饱和层；(2) 池的 expected 标签由机械配对规则（如 bigram 重叠 argmax + Jaccard 排同题阈值）生成，且预注册自带『真双适用噪声』声明；(3) 判分是逐例二元判决，错例数与阈值所需净翻转数可直接相除。这三条在零新采样的情况下即可回答『该仪器能否通过阈值』。

## Short path
- 读冻结综合/预注册，确定哪一层携带全部信号、其余层是否饱和（解决未知量：效应上限存在于哪一层）。
- 纯算术算 headroom：treatment 臂现有错例数 vs 阈值所需净翻转数；若可赢例数 < 所需翻转数，先记下『结构性不可通过』假设（解决未知量：仪器是否够格）。
- 对每个判错例做 label provenance 审计：对照池的构造规则（trap 卡自带 Trigger/Discriminator 原文 vs 呈现 trigger），把错例二分为『标签噪声』与『真实判别失败』（解决未知量：噪声地板多大）。
- 比较噪声地板与阈值：地板 ≥ 阈值/2 或可赢余量 < 阈值 → 结论=仪器无效，转入 pool 修复（双评分者裁定、purpose 级近失陷阱），机制分支全部挂起。
- 只有当每例审计显示标签干净、错误是真实判别失败时，才回到机制分支选择；并用 paired transition（谁翻成谁）而非 aggregate Δ 定位机制层。

## Stop conditions
- 已从冻结工件算出噪声地板与可赢余量，并与预注册阈值比较得出『仪器有效/无效』结论
- 每个错例都已归入且仅归入一个根因类（含『仪器噪声』类），无剩余未解释错例

## Verification
- headroom 算术可复算：treatment 错例数、每例标签归属、阈值换算成分数，全部来自冻结文件（SYNTHESIS/EXECUTION-PLAN/pool.json），零新采样
- 翻转方向清点：control错→treat对 与 control对→treat错 的计数与 aggregate Δ 一致；噪声例应双臂同为『错』且双臂理由均实质成立
- 每例噪声判定必须引用 trap 卡自带 Trigger/Discriminator 原文作证据，而非事后直觉

## Counterexamples
- 错例审计显示标签干净、错误是真实判别失败（如卡面向『写工件前取名』而任务只『核验标识符存在』的 purpose 级分歧）——此时仪器有效，不得用噪声地板搪塞，应回到机制分支
- 评分不是逐例二元判决（自由文本质量、连续分数、无 frozen per-case label），paired label audit 不适用，需改用评分者间一致性或 bootstrap
- 池已经过独立双评分者预裁定、噪声地板已知低于阈值——不要重复审计，直接做机制分析
- 结果不是近零/FAIL，而是效应清晰通过或清晰反向——headroom 问题不改变解读，不触发本方法
