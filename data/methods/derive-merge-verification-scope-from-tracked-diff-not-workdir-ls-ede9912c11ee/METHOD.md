---
method_id: derive-merge-verification-scope-from-tracked-diff-not-workdir-ls-ede9912c11ee
name: derive-merge-verification-scope-from-tracked-diff-not-workdir-ls
description: 在并发开发者活跃使用的共享脏检出区里为合并/集成分支跑聚焦验证时，聚焦集（测试、lint 目标）必须从被并入 tip 的 tracked 变更面推导（merge-base..tip 的 diff --name-only / show --stat / 治理回执 scope），而不是主工作目录的 ls 列举：未跟踪在途文件会污染目录列举，导致在干净合并 worktree 里 file-not-found ERROR 与无效重跑。同时预期未跑过闸的未推送 tip 自带作者时点 lint 债，changed-file 零红 ratchet 会拦下，用语义保持的最小 fixup 落在合并线，不改作者提交、不降闸。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8672274c-c75a-4ab5-b849-aca58f25110f:368:4b7e20f2784a8d463c82
evidence_refs: learning:learn:ca59c614da5b
created_at: 2026-10-23T04:33:45.312863+08:00
updated_at: 2026-10-23T04:33:45.312863+08:00
---
## Trigger
在共享/脏检出区（有并发开发者、含未跟踪在途文件）为合并或集成分支选择聚焦验证子集时；或聚焦测试在合并 worktree 报 file not found 需归因时。

## Discriminator
被并入 tip 的精确 tracked 变更面已在手的只读 git 输出里（更早的 show --stat / log / 回执 scope 已列出全部文件）；工作目录 ls 多出的文件不属于任一合并提交，可用合并树内存在性一键证伪为未跟踪在途工作。

## Short path
- 从状态/回执确定目标（tip 合入 main），未知量=合并线验证范围
- 用 rev-parse/log 钉拓扑与 merge-base；从早前 show --stat tip 或回执 scope 拿到精确 tracked 变更面
- 主检出区脏且被并发占用时，在隔离临时 worktree 建合并
- 聚焦集 = tracked 变更面 ∩ 测试/脚本目录，对合并树跑闸
- 闸报 changed-file lint 红（作者未跑闸）→ 定位到行，语义保持最小修复，以 fixup commit 落合并线
- 聚焦测试报 file not found → 判定为主检出区未跟踪在途工作，从聚焦集剔除并记录，不并入

## Stop conditions
- 聚焦集内全部 tracked 文件在合并树存在且相关闸（测试/ruff ratchet/pyright ratchet/env-pins/安全扫描）全绿
- 推送按准入绑定的原样命令形式执行成功，远程 ahead/behind 与预期提交数一致

## Verification
- 聚焦集每个文件对合并树 git ls-tree 核实为 tracked
- fixup 的 diff 仅触碰 lint 指名行，原断言/语义不变且测试仍过
- 推送前 fetch 权威远程，确认待推提交集合恰好等于本次合并线产出

## Counterexamples
- 单人独占的干净检出区：working-dir 列举==tracked 面，直接用 ls 选范围不会出错，方法无增益
- 任务目标就是评审并发开发者的未跟踪在途文件本身（如新测试草稿），必须读工作目录而非 tracked diff
- 仓库闸只看新增 fingerprint、无 changed-file 零红规则：作者 lint 债不会在合并时被拦，无需 fixup 分支
