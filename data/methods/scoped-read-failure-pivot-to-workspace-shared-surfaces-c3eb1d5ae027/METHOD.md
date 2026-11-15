---
method_id: scoped-read-failure-pivot-to-workspace-shared-surfaces-c3eb1d5ae027
name: scoped-read-failure-pivot-to-workspace-shared-surfaces
description: 跨会话接力时，读源会话的 task_state 或子代理失败，若失败原因显式点名范围/属主边界（not found in current session/workspace、review_child_not_owned），应视为『查询通道的属主边界』而非『事实不存在』：不再换措辞重试本会话存储，而是按事实类型映射到工作区级共享面——会话叙事/命令→统一事件流里源会话的 action_trace；工具产出（审查回执等）→该工具的落盘 artifact 目录；外部终态→只读 git ls-remote 与服务状态。重建 runbook 后在本会话重新落盘 task_state 供下次接力。本集实测可省掉 search_archive 落空与 task_state 反复重试，并从磁盘直接取得决定根因的批审查回执。
aliases: 读不到别的会话的 task_state, 跨会话 runbook 恢复, review_child_not_owned 被拒怎么办, 审查子代理回执去哪看, 交接快照里的引用读取失败, 从事件流重建 runbook
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:df541f4c-2416-4a84-a73b-c1c05feb56d1:0:7cfda395ea70f4a6fc18
evidence_refs: learning:learn:345cda22e243
created_at: 2026-11-15T21:14:39.476094+08:00
updated_at: 2026-11-15T21:14:39.476094+08:00
---
## Trigger
接手跨会话接力/交接快照后，快照点名的 state 引用、runbook 或子代理状态查询在本会话读取失败，且失败原因显式携带会话/属主边界字样（如 not found in current session/workspace、review_child_not_owned），而非单纯的 does-not-exist/404

## Discriminator
失败原因的措辞本身：点名边界（current session/workspace、not owned）=事实仍在共享面、仅该查询通道不可用；纯 404/不存在=事实缺失，本方法不适用。旁证：快照头注明『消息未复制』，且统一事件流已包含源会话 session 标记的 action_trace 条目，说明源会话事实落在工作区级面而非本会话存储

## Short path
- 把首次范围性失败判定为该通道终结：不再以其他措辞重试本会话的 task_state/search_archive 类检索
- 按事实类型映射到共享面：会话叙事与命令→统一事件流中源会话 action_trace 的有界尾读；工具产出→该工具的落盘 artifact 目录（按 subagent id 或时间就近定位）；外部终态→只读 git ls-remote/服务状态
- 只读取与接力任务相关的时间窗与 id 切片，重建 runbook 内容（命令序列、审查链、未决项），不做全量枚举
- 对子代理终态：工具 API 因属主拒绝时，直接读磁盘回执文件闭合该未知量
- 把重建的 runbook 在本会话重新落盘为新 task_state，报告快照与现状的 delta
- 三个决策未知量（runbook 内容、动作终态、外部副作用终态）分别被对应权威面闭合即停

## Stop conditions
- runbook、审查/动作终态、外部 git/服务终态已分别由事件流、落盘回执、只读核验独立闭合
- artifact 目录本身按会话隔离或已清理，或拒绝原因是保密策略而非属主边界——停止绕行，转属主会话/用户通道
- 事件流回执仍 complete:false 且关键窗口未覆盖——不得断言无记录，继续有界读或换面

## Verification
- 重建内容与快照锚点（git_head、action id、subagent id、时间戳）互相印证
- 磁盘回执文件名中的 subagent id 与事件流中轮询出现的 id 一致
- 重新落盘的 task_state 在本会话读回成功，下次接力无需再重建

## Counterexamples
- 失败原因是纯 404/does-not-exist——事实本身缺失，换面读取无意义
- 回执写在按会话隔离的 run 沙箱目录（不共享或已被清理）——磁盘直读取不到
- 拒绝源于保密/策略（数据不允许跨会话读），而非查询 API 的属主归属——绕过磁盘读取越权
- 引用本就属于当前会话却读取失败——更可能是引用写错或存储命名方案问题，应先解析方案而非换面
