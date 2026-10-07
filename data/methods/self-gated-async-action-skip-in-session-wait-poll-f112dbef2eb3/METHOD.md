---
method_id: self-gated-async-action-skip-in-session-wait-poll-f112dbef2eb3
name: self-gated-async-action-skip-in-session-wait-poll
description: 后台动作（如服务重启/发布）受理回执若披露了等待链/闸条件，先判别闸是否由当前会话自身控制（如'先等 requester 会话结束'）。若闸=自身会话退出，则终态在本回合内结构上不可达：任何 sleep/轮询只能返回 waiting_* 中间态，定时等待是纯延迟。此时至多做一次立即 status 快照确认 barriers/状态名，然后用一条回复向用户交代：action_id、两阶段闸设计、本回合退出后自动续行、下回合如何核对终态（service_control(action=status, action_id) 或 event_stream 终态查询），随后停止。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ca02bdc1-1ca9-4389-9732-e3ba796f5550:537:f5feabe565a0180cffee
evidence_refs: learning:learn:775b0992a5a8
created_at: 2026-10-07T18:34:24.582666+08:00
updated_at: 2026-10-07T18:34:24.582666+08:00
---
## Trigger
已受理一个异步后台动作（受理≠完成），且受理回执文本明确写出其等待链含'等待发起方/requester 会话结束'这类由当前执行会话自身构成的闸。

## Discriminator
受理回执是否显式披露：等待链第一闸 = requester 会话退出。是 → 终态在会话存续期间不可观测，等待/轮询必然只返回中间态；否（闸为目标服务空闲/外部事件，或回执未披露等待链）→ 会话内轮询仍可能观察到终态。该事实在 sleep 之前已完整出现在回执中（本集：'两阶段等待（web/all 先等 requester 会话结束，再等目标空闲）…受理≠完成'）。

## Short path
- 前置检查 admission_barriers/status，确认无障碍可提交（本集首次 status 查询已满足）
- 变更类调用一次性带全契约字段（target 由用户点名的服务集合给出）；若本会话未展示过该工具契约，先 get_tool_schema，避免 target 缺失式失败重试
- 读受理回执：提取 action_id、基准代、等待链描述与终态核对入口
- 判别闸条件：含 requester 会话退出 → 不做定时等待；至多做一次立即 status 快照确认 barriers/waiting_* 状态名，随后停止
- 一条回复交代：已受理、闸设计、回合退出后自动续行、下回合核对终态的具体入口

## Stop conditions
- 回执已含终态（succeeded/failed）→ 直接核对并汇报，停止
- 闸=requester 会话退出且快照已确认 barriers → 交代验证入口后停止，终态核对推迟到会话退出后的下一回合
- 闸与会话无关且用户要求当场确认 → 改为有界间隔轮询直到终态或预算耗尽（本方法不适用该分支）

## Verification
- 汇报中的 barriers/状态名必须来自 status 回执原文，且 operation_id/action_id 与受理回执一致；不得把等待链描述推断成'已发生'
- 未查询到 status=succeeded/failed 时，结论必须表述为'未完成/等待中'，不得宣布成功或失败
- 给用户的验证入口须与回执给出的入口一致且 action_id 可复现

## Counterexamples
- 闸是目标服务空闲或外部事件（与当前会话无关）：会话内 sleep+轮询是观察终态的正确手段，不应跳过
- 受理回执未披露等待链/闸条件：一次有界等待+status 查询属于合法发现而非浪费，本方法不适用
- 同步动作（回执本身即终态）：无需任何等待，也不适用本方法
- 用户显式要求本回合内盯到完成且闸条件允许：仍需受预算约束的轮询
