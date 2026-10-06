---
method_id: spec-first-execution-contract-before-infra-reuse-7a07677f7092
name: spec-first-execution-contract-before-infra-reuse
description: 执行预注册/冻结的实验或计划文档时，把该文档当作可执行契约：先从已读入的正文中提取约束执行形态的条款（臂开关机制、每臂要求的通道/engine 类别、冻结面、分析管线与裁决分支），再用这些条款筛选或否决基础设施候选。不要因为相邻任务用过某个 harness 就默认复用，也不要在条款对照之前对文件名做宽枚举找 runner。候选 infra 与条款逐条对照，不满足即当场排除，转向符合形态的实现；确有不可调和处则登记偏离，不静默改设计。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:abda90a9-c633-4664-b777-2ef993c8f7d9:175:9942508f1f89d6719b2c
evidence_refs: learning:learn:27a2249d4592
created_at: 2026-10-05T23:52:15.149508+08:00
updated_at: 2026-10-05T23:52:15.149508+08:00
---
## Trigger
任务要求执行一份带冻结声明/预注册状态的 SPEC 或计划文档，且到达基础设施决策点：正考虑复用上一个相邻任务的 harness，或准备去搜索“既有 runner/跑批脚本”。

## Discriminator
冻结 SPEC 全文已在手（此前已完整读入）：其中明文写出执行级约束——臂开关为进程 env 门控、对照臂 C0 必须是无 flag 的 headless/CLI engine、案例池与阈值冻结。该条款自读入那一刻即构成判别事实：任何 harness 候选可直接与之文本对照判定准入与否，无需先读该 harness 的历史报告或先确认“上次怎么跑的”。

## Short path
- 按精确编号一步定位预注册文档（首次搜索即唯一命中）并完整读取；未知量：执行必须满足哪些冻结条款。
- 从 SPEC 提取可执行约束清单：臂开关 env、每臂要求的通道/engine 类别（C0=无 flag headless/CLI）、池文件+sha256 冻结、禁期中分析、deterministic analyzer 与预注册裁决分支；未知量：合格 runner 的形态。
- 按约束关键词做内容级搜索，验证机制真实存在且按 env 门控（命中 gating 代码即证）；未知量：两臂能否按冻结设计实现。
- 用一次权威 runtime 快照核完全部冻结面（generation/pid/config），不换措辞重复查同一状态；未知量：生产面是否确实冻结。
- 以 spec 派生的形态关键词找 infra 候选，逐条检查其执行通道并对照条款（交互服务会话型当场排除）→选/改 headless 驱动；未知量：哪个 runner 准入。
- 按预注册顺序执行矩阵，完成后单次运行 analyzer、按 SPEC 自带分支一次性裁决，偏离全部写入偏离登记；未知量：最终裁决。

## Stop conditions
- 每条冻结执行约束都有已验证的满足实现，或已显式登记为偏离
- 矩阵按预注册行集完成、analyzer 仅运行一次并产出不可变裁决
- 冻结条款与现有基础设施不可调和时：登记偏离并呈现矛盾本身，不静默改设计凑合执行

## Verification
- SPEC 的每条执行约束都能映射到一个具体已核对事实（gating 代码行、快照字段、池 sha256），而非“看起来有”
- 最终裁决引用 SPEC 预注册的裁决分支；每一处执行偏离可追溯到偏离登记条目，而非事后解释

## Counterexamples
- 计划文档未规定执行通道/infra 形态（只定义指标与产出）——沿用相邻任务的成熟 harness 是正确默认，不必从文档推导约束
- 上一 harness 已逐条满足冻结条款（本来就是 headless 且同一 env 门控）——直接复用，无需重推导或另建
- 探索性任务、无冻结契约——先宽侦察再收敛反而合理，本方法不适用
- 冻结文档与当前代码已漂移（快照显示版本/路径不匹配、冻结凭证失效）——应先修订或重开 spec，而非照过期设计执行
