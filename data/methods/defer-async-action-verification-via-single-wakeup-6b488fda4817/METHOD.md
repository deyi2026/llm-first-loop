---
method_id: defer-async-action-verification-via-single-wakeup-6b488fda4817
name: defer-async-action-verification-via-single-wakeup
description: 当异步控制类操作（restart/publish 等）的回执明确声明两阶段等待——先等发起方会话结束、再等目标空闲——并要求勿轮询时，正确做法是：立即结束当前轮（本轮不再发起任何工具调用，尤其不要查状态），用一次唤醒/提醒注册终态检查，提醒载荷必须携带 action_id、generation 与已承诺的验证清单；唤醒后仅以 action_id 做一次终态查询，核对 live 状态等于 desired 状态。轮内轮询不仅浪费调用，还会阻塞两阶段等待自身（操作在等本会话退出）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6e0fb83b-03af-44ff-be33-c3498380b42f:1183:99cbbb672fa86d3e61ab
evidence_refs: learning:learn:9d6513069ed2
created_at: 2026-09-20T21:19:34.898275+00:00
updated_at: 2026-09-20T21:19:34.898275+00:00
---
## Trigger
异步 action 回执中出现『两阶段等待/先等 requester 会话结束/勿轮询本 action/下一轮用 status(action_id) 查终态』类协议指令，或回执的放行条件依赖发起方先退出当前轮。

## Discriminator
回执文本本身是否明确声明：(1) 等待条件依赖本会话/本轮结束才放行；(2) 明示『勿轮询，下一轮用 status(action_id=...) 查终态』。这条当时即已存在的事实把『还能继续做点什么』缩成『结束本轮 + 一次携带 action_id 的延迟检查』两个动作，任何轮内 status 调用既是重复又自我阻塞。

## Short path
- 用 status 核对 publish 落盘事实（generation、desired git_head、restart_required 及 reasons）；未知量：期望状态是否已提交、为何需要重启。
- 仅当 restart_required 且 reasons 指向 live/desired git_head 不一致时发起 restart；未知量：重启是否被受理并拿到 action_id。
- 收到含两阶段等待协议的回执后，本轮立即停止一切工具调用（不查状态、不重复发起）；未知量：如何在不阻塞的情况下获知终态。
- 注册一次唤醒，提醒载荷写入 action_id、generation 与承诺的验证清单；未知量：唤醒后要核对什么。
- 唤醒后仅执行一次 service_control(status, action_id)，核对三服务 live git_head==desired git_head，再执行承诺的功能性验证并停止控制类调用。

## Stop conditions
- 回执已给出 action_id 且唤醒已注册（载荷含 action_id 与验证清单）→ 立即结束本轮，本轮不再调用任何工具。
- 延迟 status 显示 live git_head==desired 且服务健康/pid_alive → 转入功能验证，停止控制类与发现类调用。

## Verification
- 唤醒提醒中包含 action_id 与 generation，使延迟检查唯一定位该 action，而非重新扫描服务/动作列表。
- 唤醒后的状态查询以 action_id 为参数，且全 episode 对同一 action 的终态查询不超过一次。
- 终态核对的是 live git_head 与 desired git_head 的实质一致（含 pid_alive/manifest），而非仅看 action 标记 succeeded。

## Counterexamples
- 同步即回即完成的操作（回执无两阶段等待、不依赖 requester 会话结束）——立即查一次状态即可，先结束本轮再唤醒反而多耗一轮。
- 环境中没有唤醒/调度工具可用时，不能只结束本轮而不安排任何后续，否则终态永远无人核验；需改用其他延迟机制或确认系统会主动回调。
- 回执虽异步但等待条件与发起方会话无关（如仅等目标空闲）——轮内做一次带超时的轻量状态检查不会自我阻塞，可以合理确认后再收尾。
