---
method_id: pending-in-restored-state-adjudicate-against-newer-events-243f6e633b8b
name: pending-in-restored-state-adjudicate-against-newer-events
description: Compaction 后恢复的 task_state 快照把某事项标为 pending/等待授权时，快照时间戳只是下界而非实时事实：重执行前先用 event_stream 按『任务主题词 + since=快照时间戳』查一次快照之后的事件（declaration/成功回执），裁决该事项是否已被完成并验收；同时从最近一次成功回执里提取操作参数（真实用户名/主机/通道），旧 experience/静态文档只作后备。本次 00:14 的 declaration 早已宣告安装完成且七项验收全绿，却被 23:05 的旧快照带回重新规划整套升级方案并枚举 SSH 组合。
aliases: 恢复状态说待办先查后面事件, 快照之后可能已经干完了, compaction 后 pending 不一定是 pending, 重做前先查 declaration, 旧状态卡等待授权先核事件流, 别信旧快照直接排安装计划
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:3844:fd339c6555feef95abfd
evidence_refs: learning:learn:bdbcb41faee9
created_at: 2026-11-09T00:49:46.890206+08:00
updated_at: 2026-11-09T00:49:46.890206+08:00
---
## Trigger
恢复的状态快照带明确时间戳、其清单含 pending/等待授权类事项，且当前时刻晚于快照时间戳、工作区存在可按时间与主题查询的统一事件流（declaration_check/action_trace）

## Discriminator
快照回执自带时间戳（如 2026-11-08 23:05），而事件流里可能存在更晚的 declaration/成功回执——『快照时 pending』≠『现在 pending』；同会话 compaction 前的成功 SSH 回执（含真实用户名，形如 <user>@host）本身就在事件流中，无需从静态 experience（写着 operator@）重建

## Short path
- 读状态快照，记下时间戳与 pending 清单；第一未知量=快照之后这些事项有无进展
- event_stream 按主题词（如 deepin/安装）+since=快照时间戳查一次；命中完成 declaration→该事项已闭合，从执行清单移除并按该回执登记验收
- 仍 pending 的事项才进入执行规划；执行前从事件流最近一次成功命令回执提取操作参数（用户名/主机/通道），静态 docs/experience 退为后备
- 事件流中快照后无相关事件→事项确为 pending，才按通道治理/静态文档路线重建

## Stop conditions
- 快照后事件给出该事项的完成 declaration/验收回执→停止重新执行，直接登记并转向下一个 pending
- 事件流中快照之后无该主题任何事件→pending 为真，转入正常执行规划，不再反复查历史

## Verification
- 完成回执的时间戳严格晚于状态快照时间戳（且晚于用户授权语所指的等待点）
- 最终汇报中该事项的验收凭证引用自那条历史回执，而非本轮重做产生的新凭证
- 若重做了任何操作参数（用户名/主机），能在事件流成功回执中找到逐字对应

## Counterexamples
- 快照时间戳≈当前时刻、其后无任何事件：pending 为真，直接规划执行，不必先查事件流
- 事件流中该主题只有失败尝试、无成功/declaration：静态 experience 的通道信息仍是最佳可用线索，应走通道治理排查而非继续翻事件
- pending 事项是纯本地、无事件面的琐碎改动（如补一行注释）：直接做，查事件流纯属浪费
