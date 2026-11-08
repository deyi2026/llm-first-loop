---
method_id: parent-stop-cancelled-child-is-user-pause-not-failure-40ffacba76b9
name: parent-stop-cancelled-child-is-user-pause-not-failure
description: 子代理终态回执顶层标 failure，但字段/正文显示 child_state=cancelled 且归因于父会话先前按用户指令发出的停止请求时，这不是子代理故障：不诊断、不重试、不自动重开。用 lease 确认 settled 终态后，按『评审从未产出』裁决门禁不满足，只读核对未做 commit/merge/push，如实上报因果与不可核对项（如回执无 model 字段），把重开权交还用户——自动重开等于覆盖用户的停止决定。与运行级失败（爆窗/provider/轮次上限→重切分小段）是不同失败类别分支。
aliases: 子代理是我们自己叫停的怎么收尾, reviewer 被叫停后算不算过审, 取消掉的复审还要重新拉起吗, 回显示失败其实是 stop 造成的, 父会话停掉的子代理怎么交接
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:0a79bf7c-4ae8-4f1a-be35-75280ea0a40e:411:4b19a00a8ec45a0f85d3
evidence_refs: learning:learn:57df5824ad38
created_at: 2026-11-07T13:56:28.564006+08:00
updated_at: 2026-11-07T13:56:28.564006+08:00
---
## Trigger
异步子代理终态查询回执顶层标为 failure/异常，但内嵌字段与子代理正文显示 outcome=cancelled，且正文把取消归因于『父会话停止请求』（该请求是本会话先前按用户指令发出的长链路停止）

## Discriminator
首条回执自带的三段证据：child_state/child_outcome=cancelled（非 failed、非轮次上限、非 provider 错误类别）；子代理正文逐字写明『已按父会话停止请求取消』；lease state=settled+outcome=cancelled（终态已定、非 pending，用户预留的『若仍 running 再查一次』条款不触发）。这三点在收到回执当时即已存在，足以把『子代理坏了需要诊断/重试/重开』整族分支剪掉，缩成『评审被用户暂停、从未产出结论』。

## Short path
- 读终态回执：先做失败分类——正文归因『父会话停止请求』即定性为用户暂停，排除子代理自身故障，不进入诊断
- 用 lease 查询确认 state=settled/outcome=cancelled：终态已定则不再轮询，用户预留的第二次查询条款不触发
- 按『评审从未产出』推门禁：无报告=无 PASS/REVISE 判定，门禁不满足；用只读检查核对本会话未触碰合并面（HEAD 未变、合并队列空、工作树仅原有未跟踪改动）
- 如实上报：取消因果（用户 stop 请求所致）+ 不可核对项（回执无 model 字段即声明无从核对，不推断）；记录 checkpoint
- 重开决策交还用户：取消源于用户的停止指令，自动重开子代理等于覆盖该决定；给出重开所需隔离参数，等指令后冻结其余动作

## Stop conditions
- subagent_result 与 lease 双回执一致确认终态 cancelled 且归因父会话 stop 请求
- 只读核对确认冻结面未变：无 commit/merge/push、队列空、工作树改动面与冻结时一致
- 因果与不可核对项已向用户报告、checkpoint 已记，且未重开、未重试、未再次轮询

## Verification
- lease 的 state/outcome 与 subagent_result 的 child_state/child_outcome 逐字一致（settled/cancelled）
- 子代理工具轨迹全为只读且无产出（read/search 全 success、无写操作、无报告文本），与『取消前未完成评审』解释一致
- HEAD/合并队列/工作树三项核对均为只读回执，证明门禁失败期间父会话零变更

## Counterexamples
- child_state=failed 且类别为上下文爆窗/provider 校验错误/轮次上限：走运行级失败→把剩余范围切成有界小段重派的分支，本卡不适用
- 任务书已显式授权失败/取消后自动重开评审或重试：按授权执行，不等待用户决定
- 取消回执未写明归属（无『父会话停止请求』字样）且 lease 仍 pending：按轮询预算方法继续有界等待，不要立即定性为用户暂停
- 子代理仍在 running：用户预留的『再查一次』条款生效，走有界阻塞轮询而非终态裁决
