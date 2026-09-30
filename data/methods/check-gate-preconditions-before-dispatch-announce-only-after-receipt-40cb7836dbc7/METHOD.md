---
method_id: check-gate-preconditions-before-dispatch-announce-only-after-receipt-40cb7836dbc7
name: check-gate-preconditions-before-dispatch-announce-only-after-receipt
description: 对程序托管、带前置门禁的异步操作（发布/重启/部署类）：派发前先用一条本地廉价命令核实已知门禁前置（如 tracked 树干净）；派发后不得在任何回执到达终态前向用户预告结果。回执的 status/detail/problem_kind/next_step 是权威事实——失败时按 next_step 做操作者侧处置（提交/还原由人决定，程序不做），终态 succeeded 才宣布。用户报『以前可以现在不行』时，先读最新回执再解释，不做进程级宽排查：对有结构化回执的操作，根因定位退化为读回执。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d8f59859-1341-4560-9f92-9163e49963d5:789:a8e35843ce2d27ba27da
evidence_refs: learning:learn:0c962eb096ae
created_at: 2026-09-30T13:09:08.556776+08:00
updated_at: 2026-09-30T13:09:08.556776+08:00
---
## Trigger
即将派发带程序门禁的异步生命周期操作（publish/restart/update 等），或用户报告此类操作『之前成功、现在失败』需要解释时；前提是该操作产生结构化回执（status/detail/problem_kind/next_step）且其前置条件可在本地廉价复核。

## Discriminator
派发时刻已存在、却未被使用的事实：(1) 门禁前置本地一条命令可判定——本集中 git status --short 即可发现 3 个 tracked 文件未提交，与两次失败回执的 problem_kind=tracked_worktree_dirty 完全对应，两次失败在派发前就可预测；(2) 回执本身已写明失败原因与处置边界（『需先由操作者提交或还原；程序不 stash/commit/checkout』），无需进程/日志级宽排查。

## Short path
- 用户问『为什么现在不行』：先读该操作最新 1–2 条回执；未知量=程序实际判定了什么
- 回执 status=failed 且 problem_kind 指向本地可查前置：用一条本地命令复核（如 git status --short），确认失败文件集合吻合
- 审查未提交 diff 是否就是待发布内容，再按操作者意图解除前置（提交或还原；方法不预设必须提交）
- 重新派发：首用该工具或字段不确定时先读 schema，一次性填全必填字段（本集 restart 漏 target 被拒一次，多耗两步）
- 派发后挂回执核验（轮询或定时），终态 succeeded 且 generation/HEAD 与本次提交绑定一致才答复用户；宣称引用 action_id+generation 而非预测语气

## Stop conditions
- 新派发动作回执到达终态 succeeded 且绑定 generation/HEAD 与本次提交一致，即可向用户宣布
- 回执再次 failed 但 problem_kind 已改变：换处置分支，不重复同一修复
- 最新回执 succeeded 而用户仍报异常：前置门禁不是原因，转运行时/行为探针，不要提交或还原任何东西

## Verification
- 派发前：本地前置复核命令的输出与回执 problem_kind 一致（dirty 文件集合吻合）
- 派发后：重读回执确认终态 succeeded，git_head/generation 与本次 commit 匹配
- 对用户的因果解释能引用回执原文（detail/next_step），而非推测

## Counterexamples
- 回执显示 succeeded 但用户仍见故障：门禁前置检查不适用，问题在运行时/配置生效路径，此时 commit/revert 反而有害
- 操作无结构化回执（裸 shell/systemctl 类）：没有 problem_kind/next_step 可读，应直接看该命令自身输出与日志
- 未提交改动是不打算发布的实验性改动：解除前置的正确动作是还原/暂存而非提交；方法只要求『解除前置』，不预设提交
- 前置状态被并发写者高频改变、check-then-dispatch 必然竞态：放弃派发前检查，直接派发并以回执为准
