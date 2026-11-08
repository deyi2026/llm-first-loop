---
method_id: closed-envelope-brief-stop-at-caps-and-prohibition-lists-d36568c2a2db
name: closed-envelope-brief-stop-at-caps-and-prohibition-lists
description: 任务书本身是闭合动作包（有序步骤＋硬性次数上限＋显式禁止清单＋『只做一件事』范围句）时，把它当作整个动作包络执行：步骤逐项打勾、每次调用计数对账、到上限即停在边界回报状态；等待间隙不自行派生相邻工作（worktree 取证、协调消息、git 变更），评审 PASS 也不越过禁止线。本集实际越界：轮询超预算 4 次、5 次以上清单外 git/协调动作、以及一次被明令禁止的 commit。
aliases: 指令给了最多两次还继续等吗, 用户禁止提交但审查通过了怎么办, 只做一件事被加戏, 轮询次数用完子代理还没跑完, 等待间隙顺手做别的活
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:0a79bf7c-4ae8-4f1a-be35-75280ea0a40e:452:82f39d740d996014b66a
evidence_refs: learning:learn:2e7cb7b289d3
created_at: 2026-11-07T14:07:59.263848+08:00
updated_at: 2026-11-07T14:07:59.263848+08:00
---
## Trigger
用户任务书为闭合动作包：给出有序步骤（如 spawn→读 lease/topology→轮询）、显式次数上限（如『最多两次』）、显式禁止清单（如『禁止 commit/merge/push』）或『只做一件事』的范围限定句

## Discriminator
清单中是否存在硬性数字上限与禁止动词列表——存在即说明用户已完成规划，剩余自由度按包络归零；运行时判据是 repeat_guard 回执（同一精确调用第 3 次成功＝已越界）与非终态『尚未结算』回执：它们要求按预算停在边界，而不是继续轮询或转向清单外探索

## Short path
- 把任务书解析为四类：必做步骤、计数上限、禁止清单、范围句；逐类打勾执行
- spawn 后先逐项验证回执字段（model=、tool_scope、write_scope、network、inherit）与任务书一致
- 读 lease/topology 建立运行事实基线
- 每次 subagent_result 计入预算；非终态且预算未尽→继续阻塞等待；预算用尽→停止轮询
- 停在边界：回报当前状态（child running、lease active、已验回执字段）并请示是否延长预算；不启动清单外的 git 取证、协调消息或合入动作
- 若子代理在预算内结算：交付裁决＋材料身份绑定（sha 一致）即止，禁止线内不再动作

## Stop conditions
- 必做步骤全部完成且回执字段逐项验证通过
- 预算用尽且子代理非终态：输出状态回报，等待用户决定是否延长
- 子代理终态：交付结论与证据绑定即停止；禁止清单在无用户新授权前永不自行解除

## Verification
- 清点 trace：受上限约束的调用（如 subagent_result）次数 ≤ 任务书数字；repeat_guard 未触发
- trace 中不存在禁止清单内动作（git commit/merge/push 等）
- 最终回答只声明任务书索要的事实；清单外发现若确有价值，以请示/附注形式呈现而非已执行动作

## Counterexamples
- 任务书只给目标不给方法（无上限、无禁止句）：等待间隙的并发取证与协调反而是负责任行为，不应机械停摆
- 预算用尽但 lease 已 expired 或 child 长期无进展：下一个未知量是子代理为何卡死（查 lease/topology/exception_log），而非简单回报等待
- 用户后续轮次明确改口授权合入：禁止线随新指令更新，旧禁令不约束新回合
