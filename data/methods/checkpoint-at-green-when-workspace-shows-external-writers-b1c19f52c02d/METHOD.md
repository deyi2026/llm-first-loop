---
method_id: checkpoint-at-green-when-workspace-shows-external-writers-b1c19f52c02d
name: checkpoint-at-green-when-workspace-shows-external-writers
description: 在出现外部自动化写入信号的共享工作区（同一相对源码路径复制在多个根下、evals runtime 镜像树等）里，把“定向测试首次全绿”当作持久化边界：立即用一次廉价 stash/工作分支提交固化未提交 tracked 改动并核对覆盖面，再进入下一编辑或全量验证阶段；若改动被外部回滚，先对照检查点/reflog 与幸存测试规格恢复，而不是从头重演编辑史。这样把不可控回滚引发的约 40 分钟全量重建缩为一次检查点加一次恢复。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:855926d8-3b7a-4a6d-9c5e-34631b59df2b:148:5664386f776bb0bf9e08
evidence_refs: learning:learn:348dbda3041f
created_at: 2026-09-19T08:47:46.575514+00:00
updated_at: 2026-09-19T08:47:46.575514+00:00
---
## Trigger
多轮代码实现任务中，任何 listing/search 结果显示同一相对源码路径出现在 ≥2 个工作区根（canonical src/ 之外还有 evals 结果 runtime 副本、完整性镜像树等），且本轮里程碑改动以未提交 tracked 编辑形式存在

## Discriminator
第一次内容搜索即可见：src/llm_loop/core/tool_execution_journal.py 同时命中 evals/.../runtime-*/src/、.context-integrity-wt/src/ 与 canonical src/ 三个根——这一当时已知事实表明有并发外部进程会改写该树，足以把“何时持久化”的答案从“轮末统一处理”缩到“首个绿色验证门”

## Short path
- 任务初期任何 search/listing 中检查同一相对路径是否出现在多个工作区根 → 标记外部写入风险，激活后续绿色门持久化规则
- 按正常窄范围编辑 + 定向验证推进（不因镜像副本扩大读取面，只读 canonical 根）
- 首个定向测试全绿时，立即对 tracked 改动做一次持久检查点（git stash push 保留工作区，或提交到工作分支），核对检查点确实覆盖本轮改动文件后，才进入下一编辑阶段或更宽验证
- 每个后续绿色门刷新检查点
- 若发现改动意外消失：先 diff 检查点/reflog 与幸存规格（既有测试断言即完整 spec），按幸存 spec 精确重建缺失层，而不是重推全部编辑历史

## Stop conditions
- 改动已按用户选定工作流正式 commit/merge 到持久分支
- 工作区确认单写者：无镜像根、无并发自动化迹象，且任务为一次性短任务
- 用户明确禁止在仓库内创建 stash/commit 等痕迹

## Verification
- 检查点创建后立即核对（stash list / commit sha 与改动文件列表一致）再继续下一步
- 疑似丢失时，用幸存测试作为规格逐条核对重建结果，并以 sha256/编辑回票比对可对账文件，而非凭记忆重写
- 全量验证绿后确认检查点为最新状态

## Counterexamples
- 一次性沙箱、单写者、无镜像根：每个绿门打检查点只增加开销而无风险对冲
- 任务契约要求保持工作树零痕迹（禁止 stash/commit）：应改用树外副本或明确跳过，不得违反契约
- 只读分析/检索任务，没有 tracked 文件改动，无物可持久化
- 绿门本身由环境 flaky 造成不可复现：先确认验证可复现，再把它当作持久化触发点
