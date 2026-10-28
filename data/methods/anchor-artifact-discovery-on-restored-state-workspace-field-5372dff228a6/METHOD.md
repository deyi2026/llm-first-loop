---
method_id: anchor-artifact-discovery-on-restored-state-workspace-field-5372dff228a6
name: anchor-artifact-discovery-on-restored-state-workspace-field
description: 通过恢复持久 task-state 续跑任务、且第一个未知量是『本任务产物/跑批入口在哪个目录或工作树』时，恢复回执里显式记录的 workspace/output 根字段就是权威定位锚：首个发现动作只在该锚根下做一次有界查找（find -maxdepth 或按回执描述的相对路径直拼），不要先猜习惯项目根（旧 mirror 仓库）、也不要发跨项目 glob 再逐候选验证。本集正是先猜错项目根、跨项目枚举出 3 个候选又逐一验证只有 v1，4 次调用后才回到 state 一开始就给出的锚根。锚根查空才扩大发现，并把『锚失效』当独立事实上报。
aliases: state里给了workspace还去猜项目路径, 续跑找不到目录先看state快照的workspace字段, 恢复状态的工作区字段当定位锚, 别拿旧mirror仓库当默认根找新产物, 跨项目glob前先在state锚根下有界find
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:89aa4eb4-d3e8-4612-9858-cce4b0fe5b6d:2059:241a3e5b320ff08547d6
evidence_refs: learning:learn:69f8cd4da64f
created_at: 2026-10-26T16:19:39.550511+08:00
updated_at: 2026-10-26T16:19:39.550511+08:00
---
## Trigger
恢复持久化任务状态（task-state 快照/续跑回执）后要定位本任务产物；或相对路径首查失败、正准备换用某个记忆中的绝对项目路径时。

## Discriminator
首次失败动作之前恢复回执已显式给出：顶层 workspace（工作区根）字段，以及同一回执中对产物相对路径的描述（场景文件清单、烟测输出目录、WIP 依赖状态）。这是权威 state 记录，优先级高于任何习惯性默认仓库路径。

## Short path
- 从恢复回执抽出显式根字段（workspace/output）作锚根，并记下回执描述的产物相对路径清单
- 只做一次有界定位：在锚根下按已知相对路径直拼或 find -maxdepth；命中后核对 git 状态与 state 记录（未提交 WIP、新增目录）一致
- 按回执提到的既有权威产物（manifest/烟测 report）复刻调用口径，单样本探针通过后再开全量
- 仅当锚根下有界查找为空（worktree 被清理/移动）才扩大到跨项目发现，并把『锚失效』当作需上报的独立事实

## Stop conditions
- 已在锚根定位到 state 描述的全部产物，且 git/依赖状态与 state 记录吻合
- 锚根下查找为空：停止沿用锚，核对是否存在更新版 state，再转入扩大发现

## Verification
- 最终定位路径的祖先目录与恢复回执的 workspace 字段取值一致
- 目录内容与 state 描述逐项对上（文件名/manifest 字段/烟测输出目录）

## Counterexamples
- state 的 workspace 指向已被清理的临时 worktree（锚失效）→ 应扩大发现而非在锚内反复找
- 目标产物实际交付在另一个仓库，state 记录的只是过程工作区 → 锚定位不到交付物
- 全新任务无 state 恢复 → 无锚可用，走常规发现流程
- 锚根极大（如用户家目录）且无相对路径描述 → 无界 find 本身就是宽搜索，须限深度/限模式
