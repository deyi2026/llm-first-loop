---
title: agent_followup 对短模型名多 provider 匹配失败：改 spawn_subagent 显式全名开窄审子代理
scenario: LFL 推广任务审稿链：首审子代理（spawn_subagent model=glm/glm-5.3）结算后需要窄复审 5 处修订，尝试 agent_followup 续话复用上下文
root_cause: ""
solution: agent_followup 报「模型 'X' 存在多个 provider 匹配」时，不要重试续话；改 spawn_subagent 显式 provider/model 全名开新子代理，在 task 中带上下文清单与逐项核对点（输出 FIXED/NOT_FIXED+总结论）
evidence: 本会话 agent_followup 失败回执（ValueError 原文）+ spawn_subagent subagent_3f8159a4e109 成功窄复审回执（docs/promotion/STATUS-20261026-daily41.md §四）
tags: [agent_followup, subagent, 模型解析, 多provider匹配, 推广任务]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T13:48:37.465465+08:00"
updated_at: "2026-10-26T13:48:37.465465+08:00"
---

现象：agent_followup(child_id=…) 对 glm/glm-5.3 启动的已终止子代理续话，返回 ValueError: 模型 'glm-5.3' 存在多个 provider 匹配: glm/glm-5.3, workbuddy/glm-5.3（续话通道把全名截成短名再解析，撞多 provider）。绕过：不开续话，直接 spawn_subagent(model='glm/glm-5.3', …) 显式全名开一个新的窄范围子代理，把前轮结论与待核点写进 task，验收等价（本班 d41 窄复审即如此完成，5/5 FIXED + PASS）。代价：丢前轮上下文（需在 task 里补足），换来确定性受理。n=1（2026-10-26 午班 d41）。