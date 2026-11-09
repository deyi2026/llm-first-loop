---
method_id: reconcile-local-main-against-pinned-remote-before-merge-base-01768de8afe0
name: reconcile-local-main-against-pinned-remote-before-merge-base
description: 恢复态/权威回执已钉住远端真值（origin/main=某 sha）后，在变基、合并审查、验证凭证、队列登记中确定『当前 main』时，本地 git HEAD 只是候选：fetch 后一条 rev-parse origin/main 与钉住值对账，不等即以远端值为 base 变基并全链写远端值，避免整条链锚在旧位点后被 push 审查拦截返工。本集：恢复态已记 origin/main 新值，rebase/审查/凭证仍全锚本地旧链，push 审查 P1 拦截后被迫二次变基+复审才合入。
aliases: 变基基准用远端还是本地, 合并被P1拦截返工预防, 本地镜像落后检测, 恢复状态远端head当锚点, 提交前对账远端main
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:3660:0810be1275f66860b72f
evidence_refs: learning:learn:05f54d41ec30
created_at: 2026-11-09T00:21:30.553071+08:00
updated_at: 2026-11-09T00:21:30.553071+08:00
---
## Trigger
恢复的任务状态或权威回执已记录远端权威值（如 origin/main 的 sha），随后要在变基/合并审查/验证凭证/队列登记中选定『当前 main』作为 base；或 git fetch 后需判断分支是否 up to date、本地 main 是否可当真

## Discriminator
恢复态钉住的 origin/main sha、本地 git HEAD、fetch 后 rev-parse origin/main 三者的差值：不一致这一当时已知事实即足以把 base 从『本地 main』收缩为『远端真值』；fetch 之后仅与本地 HEAD 比较得出的 up to date 不证明基于当前目标

## Short path
- 读恢复态/回执，记录钉住的远端权威值作为待核锚点
- 本地 rev-parse HEAD 并与锚点比对；不等→本地 main 仅是候选，禁止直接作 base
- git fetch 后 rev-parse origin/main（或 ls-remote）确认当前远端值；与锚点一致或更新则以远端值为准
- lane 变基到确认后的远端值，再跑测试与独立合并审查；receipt/lane 登记的 base_sha 全写远端值
- queue/confirm/push 后核对 push 回执为 fast-forward 且新 head 与凭证一致即停

## Stop conditions
- 变基、审查、凭证、队列登记的 base 已全部等于 fetch 后确认的 origin/main
- push 回执为 fast-forward、无 BLOCK，新 head 与登记一致

## Verification
- fetch 后 git rev-parse origin/main 与恢复态记录一致（若更新则采用并记录新值）
- 独立审查回执/verify receipt 的 base_sha == 实际 merge parent == 确认后的 origin/main
- 最终 push 为 fast-forward 且远端新 head 与 lane/凭证记录一致

## Counterexamples
- 恢复态未钉住任何远端值或指向其他仓库：锚点不存在，第一未知量是 fetch/ls-remote 直接读远端 ref，不能拿旧回执倒推
- 钉住值已过期且远端又前进：它只证本地≠远端，base 必须取 fetch 后的当前 origin/main
- 无远端/单写者仓库：本地 main 即唯一真值，对账无信息增益
