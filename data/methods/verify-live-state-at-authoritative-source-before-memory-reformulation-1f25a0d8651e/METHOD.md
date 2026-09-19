---
method_id: verify-live-state-at-authoritative-source-before-memory-reformulation-1f25a0d8651e
name: verify-live-state-at-authoritative-source-before-memory-reformulation
description: 用户在多步/委派工作完成后问"下一步建议"时：先读持久状态摘要（goal/checkpoint + pending 队列）确认无遗留待办，再把决定下一步的唯一未知量——外部工件的实时状态——直接对其权威源查询一次（如 PR 视图含 CI rollup）。内部 Evidence/记录自身标注 currentness=unverified，多轮改写查询词的内部检索在结构上无法验证实时状态，只适用于回溯既往决策。本例中约 12 次内存检索（多次 no-hit 改写）才转向 2 次外部权威查询，而后者才是真正决定答案的事实。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:1061:bb4d72788862ae197add
evidence_refs: learning:learn:25a89b659318
created_at: 2026-09-18T03:01:30.468384+00:00
updated_at: 2026-09-18T03:01:30.468384+00:00
---
## Trigger
用户请求状态汇报或下一步建议，且上下文中存在已注册的外部工件（PR/CI/服务/远端任务）其当前状态决定建议内容；同时内部证据的 currentness 元数据均为 unverified。

## Discriminator
get_goal 已返回 status=complete 且 checkpoints 枚举了各步骤终态；pending/schedule 队列显示唯一在途线程是某个外部工件（本例为 PR #28 的推送与 CI）。由此"下一步"只依赖一个未知量：该工件的实时状态。而每次内部检索结果都带 currentness=unverified 标记——这是当时即可见的事实，足以判断继续在内部存储里改写查询词不会产生决定性证据。

## Short path
- 读 goal/checkpoint 记录：未知量=是否还有未完成主线步骤（本例 complete，1→2→3 均有 checkpoint 佐证）
- 读 pending 队列（schedule/evolution/review）：未知量=是否有挂起唤醒或待审事项；无则唯一剩余未知量收敛为外部工件实时状态
- 对该工件用其自身权威接口查一次（如 gh pr view 含 statusCheckRollup）：未知量=实时 open/merged/CI 终态
- 必要时同一工件一次支撑核查（如 head 是否包含 base tip）：未知量=合并安全性/基线漂移
- 由 goal 记录 + 实时状态推导有序下一步并停止；既往汇报仅在需引用结论时定点读取一次，不做改写式宽搜

## Stop conditions
- 决定下一步的实时状态已由工件自身权威接口验证（而非内部快照推断）
- goal 与 pending 队列均无遗留待办，且实时查询结果与最后一条 checkpoint/完成汇报一致——此时可给出建议并停止检索

## Verification
- 实时权威查询结果与最后一条完成汇报/checkpoint 交叉一致（如 CI 全绿在汇报与实时 rollup 两处同源出现）
- 给建议前确认 pending_actions/schedule 无挂起项，避免建议与在途委派工作冲突

## Counterexamples
- 用户问的是既往决策或理由（"当时为什么这么定"）：内部 memory/archive 检索才是正确来源，实时系统不含该信息，本方法不适用
- 外部系统不可达、或实时查询具有破坏性/高成本：应退回内部证据（明示 unverified 时效性）并请用户决断，而非强行外查
- 委派任务可能在最后 checkpoint 之后才完成（快照可能过时）：允许一次定向 event_stream 读取补齐，但仍不应做多轮改写查询词的宽搜
