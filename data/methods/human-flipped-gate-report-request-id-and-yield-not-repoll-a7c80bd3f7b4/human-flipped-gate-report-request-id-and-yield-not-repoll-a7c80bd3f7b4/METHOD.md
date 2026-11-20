---
method_id: human-flipped-gate-report-request-id-and-yield-not-repoll-a7c80bd3f7b4
name: human-flipped-gate-report-request-id-and-yield-not-repoll
description: 受管链停在人工签发点：审批回执明示『待人工审批』并给出外部面板入口与 request_id 时，pending 的唯一翻转者是对话中的用户，不是等待工具或自动管线。此时对固定上限的等待工具反复重试既不推进状态也不产生新信息——第一次超时已确认『尚未批』这一事实。正确动作：等待调用至多确认一次 pending，随即把 request_id、批准入口、批后既定动作序列一次性回报用户并让出；收到批准信号后再取回凭据继续。判别核心是『谁能翻转这个状态位』：机器/管线翻转→轮询有信息量，按预算继续；人翻转→对话才是等待通道，工具轮询是死循环。
aliases: 审批等人批就先喊人，别空等, 等人批面板别反复超时, 先把审批单号报给用户再挂起, 用户回复已批再继续走链, human gate 卡住让出等信号
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d901b48e-25bf-45f0-a33f-23eaa879ddc3:871:0b12dd788af24c6de1fc
evidence_refs: learning:learn:0e32f74fcdfa
created_at: 2026-11-19T21:20:44.107885+08:00
updated_at: 2026-11-19T21:20:44.107885+08:00
---
## Trigger
升级/审批类回执显式声明待人工审批（附外部面板操作入口与 request_id），其后对上限式等待工具的重试只重复 pending/timeout、回执无任何新字段。

## Discriminator
进入轮询前回执已声明状态翻转者是人工面板操作（即对话中的用户本人），且等待工具只有固定超时上限、自身不推进状态；同一 episode 内子任务查询能返回 running→completed 的推进，对照证明只有翻转者是机器时轮询才携带信息量。

## Short path
- 提交审批/升级后先读回执：谁批、在哪个入口批、request_id 是什么。
- 回执若明示人工面板操作：做一次等待调用，确认 pending 且无新字段（顺带确认超时上限行为）。
- 首次超时/仍 pending 即停止轮询：把 request_id＋批准入口＋批后动作序列一次性回报用户，让出执行权。
- 收到用户批准信号后，用一次等待调用取回凭据（verify_ref 等），按既定序列恢复链路。

## Stop conditions
- 等待回执 pending 且翻转者已确认为人工 → 回报后让出，不再重试等待工具
- 等待调用直接返回凭据/已批 → 立即继续链路，无需回报等待
- 用户在对话中给出批准信号 → 恢复执行
- 任务书明令轮询到终态且终态由管线产生 → 本方法不适用，按轮询预算继续

## Verification
- 等待工具同参重试 ≤2 次，且每次回执仅重复 pending、无新字段
- 让出消息同时含 request_id、批准入口、批后动作序列三项
- 恢复后取得的凭据与原 request_id 关联一致

## Counterexamples
- 子代理/管线轮询：状态自行推进（running→completed），翻转者是机器——按预算继续轮询（本集前段 review child 两次查询即到终态）
- 任务书明令轮询到真实终态且终态由管线产生：防重复护栏不构成停止理由，应加厚等待继续（另一张卡的适用面）
- 回执声明审批自动或秒级到达（自动签发服务）：轮询仍是正确通道
- 用户不在对话回路（后台批量 run）：无法向用户让出，按任务书预算处理并落盘状态
