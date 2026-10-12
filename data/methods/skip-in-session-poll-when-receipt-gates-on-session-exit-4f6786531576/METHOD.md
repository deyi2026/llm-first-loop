---
method_id: skip-in-session-poll-when-receipt-gates-on-session-exit-4f6786531576
name: skip-in-session-poll-when-receipt-gates-on-session-exit
description: 后台异步动作（如服务 restart）的受理回执若声明自指门控——'先等 requester 会话结束，再等目标空闲'——则当前会话存活期间终态结构性不可达：会话内 wait+status 轮询只能重复看到 pre-gate 状态（如 waiting_for_requester_exit），无信息增量；且 failed 终态会保留待确认，不会被错过。正确路径是：从回执提取 action_id、门控语义与点名核对入口/期望值，直接注册门后（唤醒后）的终态核对并如实汇报'已受理未完成'，省掉会话内等待轮询轮。本集在受理回执已写明两阶段语义后，仍做了一次 45s wait + 一次 status 查询，结果必然是 waiting_for_requester_exit，随后才注册本可立即注册的排程核对。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:1264:166359007923be4be11a
evidence_refs: learning:learn:bc2e37e16c3f
created_at: 2026-10-12T10:07:02.234940+08:00
updated_at: 2026-10-12T10:07:02.234940+08:00
---
## Trigger
后台异步动作已受理（accepted≠完成），且受理回执声明其执行前置条件依赖当前会话自身生命周期（requester 会话退出/请求方空闲类门控），而本会话仍将继续运行。

## Discriminator
受理回执文本本身已写明门控语义与核对契约（'两阶段等待：先等 requester 会话结束'、'受理≠完成'、终态核对入口、failed 保留待确认直到显式闭合）。由于 requester=当前会话且尚未退出，wait+poll 必然只能返回 waiting_for_requester_exit 而非终态——该结论在发起等待前即可从回执推出，无需轮询验证。

## Short path
- 读受理回执：提取 action_id、门控语义、回执点名的终态核对入口（service_control action=status / event_stream）与绑定期望值（generation、git_head、pid_alive）。
- 判断门控是否依赖当前会话生命周期；若依赖（requester=本会话），跳过会话内 wait+poll 轮。
- 立即注册一次门后（会话结束/唤醒后）的终态核对，核对项逐条取自回执，不自行发明。
- 如实汇报中间态：'已受理、未完成'，终态由排程核对后回报，不提前宣布收敛。
- 到点用回执点名入口核对：各服务 succeeded 且 generation/git_head 匹配才宣布收敛；failed 则读 barrier/日志定位后再汇报。

## Stop conditions
- 回执声明动作立即后台执行、无会话门控 → 本方法不适用，改用有界 wait+poll 及时捕捉早失败。
- 会话内轮询或事件流出现回执语义不允许的状态（如未退会已 succeeded/failed）→ 门控模型被证伪，重新核实系统语义后再规划。
- 已按回执期望值核对到 succeeded 且关键绑定值全部匹配 → 停止推进，宣布收敛。

## Verification
- 终态核对必须使用回执点名的入口和 action_id，不得凭受理回执本身宣布完成。
- 核对项与回执绑定值一致：各服务 status=succeeded、generation=目标代、git_head=目标提交、pid_alive=true。
- 未取得 succeeded/failed 终态前，所有对外表述保持'已受理、未完成'。

## Counterexamples
- 回执声明动作立即后台执行（无 requester-exit 门控）时，有界 wait+poll 是捕捉早期失败的正确路径，不应跳过。
- 系统无 schedule/唤醒能力时，'改排程'分支不可用，只能如实汇报已受理未完成，而非套用本方法。
- 轮询返回与回执语义矛盾的终态（门控未过却已 succeeded/failed），说明对门控的理解有误或系统语义变更，应重新核实而非继续按回执语义排程。
