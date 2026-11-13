---
method_id: frontload-safe-command-forms-and-round1-parallel-batch-into-child-forens-d9ac1d3ae636
name: frontload-safe-command-forms-and-round1-parallel-batch-into-child-forensic-brief
description: 向短寿命独立子代理委派只读取证清单（发行候选复审类）且运行时合同包含写侧前置护栏、紧凑轮次预算、终态即租约失效时，取证姿势必须由父侧前置写进 spawn 任务书：命令形式约束（单命令单调用、无重定向/管道、避开被判隐式写的子命令如 git branch）＋时序约束（第1轮一次性并行发出全部清单取证、第2轮零调用纯终稿、不依赖续话）。child 在运行中自行试错会烧光轮次预算只换回零证据 fail-closed BLOCK；每次通道故障重试都把回执命名拒绝码折进下一次任务书，控制项零放宽，儿童链完整披露；附真实缺陷证据的 BLOCK 不得重试。
aliases: 子代理命令被写侧护栏拦截怎么重试, 复审child取证全被拒不放过, 子代理轮次不够被迫提前收口, child第一轮并行发全部取证命令, 续话租约失效后重开子代理, spawn只读reviewer避坑清单
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0cc80234-c7ae-4f4d-bb9a-de315c1ac2e8:0:e38648915c2ec272e181
evidence_refs: learning:learn:25536a0268d5
created_at: 2026-11-13T08:03:36.353962+08:00
updated_at: 2026-11-13T08:03:36.353962+08:00
---
## Trigger
需要 spawn 独立子代理执行只读取证/审查清单，且 schema 或先前回执已暴露运行时合同：requires.tools 程序级白名单＋写侧护栏对 shell 重定向/部分 git 子命令做对象级前置拒绝、max_rounds 紧凑且轮次是收敛预算而调用可同轮并行、fleet lease 在终态后失效导致续话 refused。

## Discriminator
回执中可见的合同事实：spawn schema 自述'程序级强制白名单、授权只降不升、spawn 成功≠完成'；child 回执逐条列出被拒命令与命名拒绝码（如 write_target_outside_scope: /dev/null、implicit_write_target: git branch）；rounds=2/tools=6 表明轮次独立于调用数（可并行）；续话 refused 回执明示租约失效。任一此类回执出现即证明姿势无法由 child 在预算内自摸，必须由父侧编码进任务书。

## Short path
- 读 spawn_subagent/subagent_result schema，提取运行时合同事实（白名单强制、轮次预算语义、续话/租约语义），将其当判别事实而非背景。
- 任务书三件套：显式编号取证清单；命令形式约束（单命令单调用、无重定向/管道、避开护栏判写子命令如 git branch，用 rev-parse --abbrev-ref 替代）；时序=第1轮并行发出全部取证调用、第2轮零调用出终稿，不依赖续话。
- 以原隔离控制项 spawn（零放宽）；有界轮询至真实 completed 终态。
- 若终稿为仅因通道故障的零/近零证据 BLOCK：把本次回执命名拒绝码逐条折进任务书后单次中性重试（控制项不变，child 仍可如实 FAIL/BLOCK），儿童链完整披露。
- 取得覆盖全清单、逐项有成功调用支撑的终稿即停止；父代理只做 child 点名的机械事实闭合，不充当 Reviewer。

## Stop conditions
- 真实 completed 终态 child 出具覆盖全部清单项且逐项有成功取证调用支撑的 PASS/FAIL 终稿。
- 任务书已编码全部已知拒绝码约束仍复现通道故障：如实以 BLOCK+完整儿童链报告，不再增加 spawn。
- child 的 BLOCK 附有真实缺陷证据：接受结论，禁止重试（结论选购）。

## Verification
- 终稿含 child_id、model_used、终态、tools 成功/失败计数，且分类与工具轨迹一致。
- 逐清单项映射到一次成功调用，缺口项有 file:line 或明确缺口声明。
- 每次重试任务书的新增约束与上一 child 的命名拒绝码一一对应（可审计）。
- 各次 spawn 控制项逐字段相同（零放宽），失败链路在最终报告完整披露。

## Counterexamples
- 取证项间存在数据依赖（下一步命令取决于上一步输出，如先从脚本读出 endpoint 再取对应 response）时无法第1轮全并行，应改用分段委派而非批量时序。
- 运行时无写侧前置护栏、或终态后租约仍允许续话时，串行节奏不是失败模式，无需前置工程化。
- 一两句调用即可完成的简单委派，命令形式约束与批量时序属过度设计。
- 父侧自己就能机械完成、无独立性要求的核验不应委派，也不适用本方法。
