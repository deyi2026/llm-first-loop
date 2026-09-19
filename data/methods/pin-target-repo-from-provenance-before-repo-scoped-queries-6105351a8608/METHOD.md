---
method_id: pin-target-repo-from-provenance-before-repo-scoped-queries-6105351a8608
name: pin-target-repo-from-provenance-before-repo-scoped-queries
description: 在多 remote 的 git 仓库里执行既定计划时，任何 repo 级 gh/api 查询（PR 状态、checks、分支保护）之前，先用已存在的 provenance（goal/plan 记录中的 '<remote>/<branch>'，或 git remote -v）确定目标 artifact 属于哪个仓库，并用 -R 显式指定。默认 remote 上的 404 或 'Branch not protected' 可能是仓库错配伪装成有效答案，会误导后续决策（如跳过 review）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:855926d8-3b7a-4a6d-9c5e-34631b59df2b:854:12dea737c7f715aa9961
evidence_refs: learning:learn:a6e6c161e05d
created_at: 2026-09-19T11:04:30.448298+00:00
updated_at: 2026-09-19T11:04:30.448298+00:00
---
## Trigger
执行一个已记录的多步计划，目标 artifact（PR、分支、保护规则）位于多 remote 仓库，且 gh 默认仓库不一定拥有该 artifact（如默认 remote 是镜像/legacy 仓库）。

## Discriminator
goal checkpoint 在任何 gh 调用之前就已写明分支被 push 到 remote 'lfl'（lfl/fleet-reclaim-fence-20260919）并创建了 draft PR——目标仓库当时已知；而 gh 默认 remote 'origin' 指向另一个 legacy 仓库。

## Short path
- 从 goal/plan 记录中读取目标 artifact 所属的 '<remote>/<branch>'（未知量：PR #44 在哪个仓库）
- git remote -v 把 remote 别名映射为具体 repo slug（未知量：gh -R 应填什么）
- 一次性对确认的 slug 发出全部 repo 级查询：gh pr view -R <slug> + 分支保护 API（未知量：PR 状态、是否需要 review）
- 按结果推进计划：ready → merge base 进 head → push（未知量：BEHIND 是否消除）
- 门禁等待用后台 job 轮询，因为 checks 需数分钟而 execute_command 有 60s 硬超时（未知量：门禁完成）
- merge、本地快进、发起重启；重启被受理即停，剩余事项移交下轮

## Stop conditions
- 所有 repo 级事实（PR 状态、保护规则、checks）均来自已确认的目标仓库，且计划的 merge/restart 步骤已被受理
- 目标仓库身份一旦确认，不再对其他 remote 重复查询同一事实

## Verification
- 解释任何查询结果（尤其 404 / 'Branch not protected'）之前，先核对 -R slug 与实际接收分支 push 的 remote URL（git remote -v）一致
- 确认 404 是目标仓库上的真实状态而非仓库错配，才将其作为决策依据

## Counterexamples
- 单 remote 仓库且默认仓库显然拥有一切——解析步骤纯属开销，直接查询即可
- 记录中的 remote 别名在 checkpoint 之后被改名/删除——provenance 边已失效，需先 git remote -v 核验，断裂时回退到显式查找
- 纯本地操作（worktree、git log、本地服务状态查询）不需要仓库定位
