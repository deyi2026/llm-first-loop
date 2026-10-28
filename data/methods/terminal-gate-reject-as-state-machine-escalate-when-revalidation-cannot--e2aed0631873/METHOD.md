---
method_id: terminal-gate-reject-as-state-machine-escalate-when-revalidation-cannot--e2aed0631873
name: terminal-gate-reject-as-state-machine-escalate-when-revalidation-cannot-fire
description: 终局硬门（goal complete/收口写）以 reason_code 拒绝并点名实体时，不要按门建议的补救出口盲试重试，也不要先用事件流做历史重建式宽探查。先读被点名实体的权威记录确认状态，再读门实现中该 reason_code 的再校验触发条件：若触发条件（如『仅转 done 时校验』）在实体当前终态（如 cancelled）下不可能满足，则程序侧出口结构性不可行，立即按门给出的人工出口升级为用户二选一决定（授权 waive / 保持不收口），全程 append-only 留痕、绝不手改账本绕门。可省去注定失败的补证据重试与多轮历史探查。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:1400:f50925e8d477e5fc50c4
evidence_refs: learning:learn:d2df09f764a9
created_at: 2026-10-15T08:23:29.250497+08:00
updated_at: 2026-10-15T08:23:29.250497+08:00
---
## Trigger
goal/PR/收口类终局写操作被硬门拒绝：回执含机器可读 reason_code、被点名的实体 id，并给出『程序侧补救 / 人工确认』两类出口；或已按门建议的补救重试一次后仍被同一 reason_code 拒绝。

## Discriminator
两件当时即可得的事实：①被点名实体的权威记录状态——若处于非 done 的终态（cancelled/archived），且 frontier 计数暴露 limbo（open+done<total）；②门实现中再校验的触发点——若校验只挂在特定状态转移（如转 done）上，该终态下任何补救动作都不会重新触发校验。二者同时成立即证明程序侧出口结构性不可行，唯一剩余出口是门所命名的人工授权。

## Short path
- 门拒绝后直接读被点名实体的权威磁盘记录（任务日志/存储）；未知量：它为何被卡。确认状态（如 pending→cancelled）、evidence_required 属性、是否重复建单。
- 若实体为非 done 终态，读门实现中该 reason_code 的校验触发条件；未知量：程序侧出口是否可能生效（本例：校验仅挂 done 转移，cancelled 恒 not_checked）。
- 触发条件在当前状态不可满足 → 停止同类补救重试，按门的人工出口升级：向用户提交含实体 id、当前状态、已试补救与两次拒绝回执、门原文出口的二选一决定（授权 waive 后 append-only 记录留痕再重试 / 保持 active 记 checkpoint 收束）。
- 不手改任务日志/审计账本绕门；用户授权后执行一次，以门的新回执为验证标准，而非任务图表面终态。

## Stop conditions
- 已确认门的再校验触发条件在实体当前终态下不可能满足——立即停止一切程序侧补救重试。
- 已向用户提交明确的 waive/不收口决定请求并等待授权，不再自行尝试出口。
- 若权威记录显示实体实为可转移状态（pending/in_progress）或阻塞源于自己可修的数据（如错误 ref id），转入正常补救路径而非升级。

## Verification
- 门实现的校验触发点与实体当前状态逐项比对：不兼容即证明程序侧出口不可行（如校验仅挂 done 转移而实体已 cancelled）。
- 升级请求内必须自足：实体 id、当前状态、已试补救及结果、门的原文出口——用户无需重查即可决策。
- 授权执行后以门的成功回执为准（complete 写入成功），不以任务图外观或口头结论为准。

## Counterexamples
- 实体处于 pending/in_progress 等可转移状态：补齐 evidence_refs 后再校验会正常触发，应直接走程序侧出口，读门实现是多余动作。
- 拒绝由瞬时故障（锁竞争、网络超时）造成且无确定性 reason_code：先做一次廉价重试即可，无需状态机分析。
- 门未提供人工出口且阻塞源于模型自己可修的坏数据（如填错的 ref id/缺失字段）：修数据重试而非升级。
- 门为不可读源码的外部服务：无法读触发条件时，退化为有界黑盒诊断（最多一次输入显著变化的探测），其余原则不变。
