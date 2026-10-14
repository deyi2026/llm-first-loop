---
method_id: self-gated-async-action-end-turn-and-schedule-terminal-verify-a2ac1aaaf9ba
name: self-gated-async-action-end-turn-and-schedule-terminal-verify
description: 受控异步两阶段动作（restart/update 类）被门禁卡住时，若回执证明阻塞条件就是当前活跃会话自身，run 内继续 wait/poll 只会续命阻塞：应注册到点唤醒做终态验证并立即结束回复，让物理阶段在 run 结束后执行。配套两条前置纪律：变更类调用前先读工具 schema（一次拿到复合单语义动作、必填字段与门禁语义，替代猜参数试错）；restart 前先核对 desired 绑定代码是否已含待生效提交，落后则先 publish/update，避免裸 restart 复活旧代码。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:775390eb-191e-4f71-9b0c-745ac8f072db:237:31929a561ea43d3c9911
evidence_refs: learning:learn:a53a668d03b4
created_at: 2026-10-14T09:51:30.661709+08:00
updated_at: 2026-10-14T09:51:30.661709+08:00
---
## Trigger
受控异步两阶段动作（restart/update 类）已受理后进入门禁型状态（waiting_for_requester_exit / waiting_for_idle），需要决定继续轮询、override 还是结束回合时；以及首次对多动作生命周期控制面工具发起变更类调用之前。

## Discriminator
自阻塞三联征（均为当时可见）：status 回显 gate=waiting_for_idle 且 updated_at 跨两次查询冻结；requester_session_id==当前会话；工具 schema 已写明该门禁等待 requester 会话结束/目标空闲，而本会话的活动正是目标服务的当前负载。三者合取可推出：run 内任何 wait/poll 都在续命阻塞条件，门禁只会在本回复结束后通过。

## Short path
- restart 类指令先做只读 status + git 核对 desired 绑定：若 desired git_head 落后于工作区 HEAD（待生效提交不在其绑定内），必须 publish/update 而非裸 restart，否则重启到的仍是旧代码
- 对变更类 action 首次调用前先 get_tool_schema：一次取得必填字段（如 code_root）、复合单语义动作（update=publish+restart）与门禁语义，替代猜参数的失败-重试
- 按 schema 前置条件准备（tracked 树干净则按仓库先例做机械收口提交），单次 update 固化 desired 并派发物理重启，附可审计 reason
- 门禁=waiting_for_requester_exit 且用户本轮指令已显式授权 → 立即 override 举证推进，不重演上轮干等到 failed 的模式
- 门禁=waiting_for_idle 且命中自阻塞判别 → 停止 run 内 wait/poll；注册到点唤醒（提示词写明期望 generation/git_head 与 succeeded/卡住/failed 三分支报告要求），随即结束本轮回复
- 唤醒后一次 status 读取终态并按分支向用户报告，不再追加确认性轮询

## Stop conditions
- status 已出现终态（succeeded/failed），或门禁不再自阻塞（requester≠当前会话、updated_at 在推进）
- 唤醒后的终态验证与用户报告已完成一次即停止，不因'再确认一下'重复查询

## Verification
- 唤醒时 status(action_id) 核对：动作终态、deployment_generation==期望 desired 代、git_head==发布提交；succeeded 再核服务进程新 pid/started_at 与代数匹配
- 若唤醒后仍 waiting_for_idle 且 requester 仍是本会话：如实报告空闲判定未过/会话未真正结束，不虚构完成

## Counterexamples
- 门禁等待的是其他会话或 owner（requester_session_id≠当前会话）：结束自己的 turn 不会解除阻塞，应轮询、adopt/release 或协调 owner
- updated_at 冻结源于 worker 已死（worker_pid 无对应进程）：需要 release/adopt/重新派发动作，而非等 turn 结束
- 本会话活动不构成目标服务的负载（如目标是不相关的外部服务）：waiting_for_idle 可能在 run 内自行通过，应再查一次 status 再决定是否结束回合
- 同步调用、无两阶段门禁的简单重启：内联等待即可，排程唤醒只增加往返
