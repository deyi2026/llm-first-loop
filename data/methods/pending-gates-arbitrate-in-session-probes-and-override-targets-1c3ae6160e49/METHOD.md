---
method_id: pending-gates-arbitrate-in-session-probes-and-override-targets-1c3ae6160e49
name: pending-gates-arbitrate-in-session-probes-and-override-targets
description: 受控异步动作（restart/deploy）回执声明多阶段门序（先等 requester 退出→再等目标空闲）或给出 pending_gates 时，当前 pending 的门是本会话行动资格的唯一判据：override 只能命中此刻 pending 的门，对后段门发起必被拒（gate not currently pending）；依赖换代后状态的探针（如 review admission）在门链终端事件前必然执行旧代码、复现旧拒绝签名。据此把断点计划二分为『现在可做／结构性推迟』，只做前者；推迟项（含对后段门的 override）写入下一 run 待办后结束回合，靠会话退出推进门链，而不是用注定失败的调用试错。
aliases: 闸还没轮到就别提前放行, 重启没落地就跑准入测试必撞旧规则, 等自己会话退出的门在会话内推不动, gate 尚未 pending 的拒绝后还要不要试, 换代受理不等于完成时本回合还能做什么
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c5f52ba4-0dd0-440d-ab8e-d4b02bb2ed41:2512:9d270ac67d5af726b44a
evidence_refs: learning:learn:9c6956dc2991
created_at: 2026-10-26T15:02:37.109375+08:00
updated_at: 2026-10-26T15:02:37.109375+08:00
---
## Trigger
异步两阶段动作受理回执含 pending_gates 或显式『先 A 再 B』门序描述；或上一同目标动作 failed（busy／等空闲超时）后准备重发或 override；或断点计划里存在依赖该动作完成才成立的验证步骤（admission／探针／全量测试）。

## Discriminator
回执中的 pending_gates 数组、显式门序描述、或恢复状态里『生效必然在下一 run』类断言。任一在场即可在发动作前判定：不在 pending 列表的门必拒 override；requester-exit 门未过时，任何依赖新状态的探针必看旧态。

## Short path
- 先按 action_id 查上一动作终态（status/event_stream），拿到 failed 详情与 reason_ref，期间不做任何依赖其结果的调用
- 需要则重发动作一次；从新回执读 pending_gates 与门序，确定当前所处阶段
- 把计划步骤二分：不依赖门链终端状态且不越阶段的=现在可做；依赖新代码生效的探针、对未 pending 门的 override=结构性推迟，从本回合剔除并写入下一 run 待办（标注『waiting_for_idle 实际 pending 后再 override』）
- 执行剩余可做项（终态核对、checkpoint、向用户交代），结束回合让会话退出推进门链

## Stop conditions
- 计划剩余步骤全部落在被推迟类 → 立即收口结束回合，不再发探针或 override 试错
- pending_gates 显示目标门已实际 pending（requester-exit 阶段已过）→ 该 override 本回合有效，执行并核验终态

## Verification
- override 回执的 pending_gates 字段即资格预言：目标门不在列表必拒，被拒后不得原地重试同门，只能等阶段推进
- 被剔除的探针若仍执行，其结果只可用于确认旧签名（如 review_untracked_file_limit 复现＝仍在旧态），不作为推进依据

## Counterexamples
- 当前 pending 的正是目标门（requester 不是锁持有者、会话退出阶段已过）→ override 或等待在会话内可行，提前收口反而拖延
- 步骤不依赖门链结果（纯 git／工作树检查、状态读取）→ 与门阶段无关，照常执行
- 单阶段、无 requester-exit 自门的普通异步动作 → 不适用，按常规终态轮询与回执句柄处理
