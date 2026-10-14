---
method_id: ci-push-failure-attribution-via-ref-tip-timestamp-and-exact-sha-repro-d6f6eb7d49b9
name: ci-push-failure-attribution-via-ref-tip-timestamp-and-exact-sha-repro
description: 收到 push 事件的 CI 失败通知但本会话未 push 时：fetch 回执『[up to date]/远端无新增提交』不能推出『main 没被 push』——他人可能 push 了本地镜像已有的提交。判别法：对 refs/remotes/origin 按 tip 提交时间排序，时间紧邻 CI 事件且其余 ref 明显更旧的即触发源；再读 workflow on: 过滤器确认。复现必须在触发 SHA 的独立 detached worktree 上按 CI 顺序只跑 failing 步骤；diff/ratchet 型门禁在本地 HEAD 领先时会误判 PASS，本地绿灯不是反证。CI 秒挂说明后续步骤未运行，无需全量测试矩阵解释未跑到的步骤。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:33d3039e-2906-4f07-9dc7-517532290686:283:3a7d19ea6a93942c2c15
evidence_refs: learning:learn:a606c0eb3b5f
created_at: 2026-10-14T18:16:17.296606+08:00
updated_at: 2026-10-14T18:16:17.296606+08:00
---
## Trigger
收到 CI 失败通知（push 事件）但触发源不明：本会话未做过 push，或本地 fetch 显示远端无新增提交，或失败可能来自他人/其他分支的 push

## Discriminator
fetch 后本地即可查询的远端 ref tip 提交时间（git for-each-ref --sort=-committerdate refs/remotes/origin）：tip 时间紧邻 CI 事件、其余 ref 明显更旧的那个 ref 即触发 push。『[up to date]』只说明本地镜像已包含该提交，并不排除『他人今日 push 了我已有的 SHA』

## Short path
- fetch + 本地/远端 delta，确认已跟踪 ref 是否移动（可能为空，空不等于无 push）
- 对 origin/* 按 committerdate 排序，取 tip 时间最接近 CI 事件的 ref 作为触发源假设（本集：origin/main 今日 16:43，其余全为九月）
- 读 workflow 的 on: 触发过滤器，验证该 ref 的 push 是否会触发这些 job（无分支过滤则任意 push 都触发）
- git worktree add --detach <触发SHA> 于独立目录，按 CI job 顺序只复现 failing 步骤（安全扫描→ruff→…），失败输出即根因材料
- 用 git log -- <file> 把违规/超限文件归因到引入提交，并检查该缺陷 blob 是否存在于所有待 push 树（区分『我引入』vs『任何人 push 都挂』）
- 修复基于本地最新 main 落分支；以与 CI 相同命令验证原 failing 步骤 + 受影响文件测试；push 决策交还用户

## Stop conditions
- 每个 failing CI 步骤都在触发 SHA 上复现并归因到具体提交/文件
- 修复分支以 CI 同口径检查通过（如 changed_file_diagnostics=0、扫描 PASS）即停，不启动全量测试矩阵去解释 CI 根本没运行到的步骤
- 触发源、根因、修复、待 push 队列四项事实齐备后停止调查

## Verification
- 触发 SHA 的 tip 提交时间与 CI 事件时间吻合，且该 SHA 确在远端 ref 上
- 本地复现的失败 job/步骤/报错与 CI 通知逐项对应
- ratchet/diff 型门禁必须用 CI 检出的确切 SHA 复现；本地领先 HEAD 上的 PASS（changed-file 基线不同）不能作为『CI 不该挂』的反证

## Counterexamples
- 事件是 pull_request/schedule/workflow_dispatch 而非 push：触发源在事件负载或 merge ref，ref tip 时间戳排序不适用
- re-push 同一 SHA 或 fast-forward 不改写 tip 提交时间：时间戳只是启发式，多个 ref 同日时需 CI run 详情/reflog 消歧
- 本会话自己刚 push 过：直接在自己 push 的 SHA 上复现，无需触发源归因枚举
- 门禁是全量非 diff 型（纯 pytest、全树检查）：本地 HEAD 与 CI 结果一致，不需要 detached worktree，但仍须按 CI 顺序复现 failing 步骤
