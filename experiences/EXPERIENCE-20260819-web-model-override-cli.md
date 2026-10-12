---
title: 指定会话（飞书/Web）模型跟随配置最短路径：model_override 排查 + CLI 写入
scenario: 用户反馈某端（如飞书）回复用错模型（如默认装配 flash），需要跟随其他会话（如绘画/Web）使用的大模型时；或需要把某会话锁定到指定模型时。
root_cause: 飞书端是独立会话，按 .env 默认装配启动（LLM_MODEL=deepseek/deepseek-v4-flash）；会话 JSON 的 model_override 字段持久化了模型锁定，不跟随其他会话的模型切换。
solution: "①排查：读目标会话 JSON 的 model_override 字段确认锁定模型（根因通常是会话级 override 锁死）；用 python 统计会话 messages 的 model_used 分布，确认\"实际主用模型\"（如绘画会话 pro 9 次 vs flash 3 次 → 绘画大模型是 pro）。②取完整会话 ID：ls data/sessions/--Users-yyj-Project-llm-first-loop--/ 下 JSON 文件名全量 ID（CLI session-list 只显示 8 位前缀，直接传给 --session 会报[会话不存在]）。③合规写入：printf '' | .venv/bin/python -m llm_loop.cli --session <完整ID> --model <provider/model> —— 空输入管道让交互模式写 override 后立即 EOF 退出，不触发 LLM 调用；回执确认\"模型已切换: X → Y\"。④验证：重读 JSON model_override 字段已更新。⑤生效：下一轮 LLM 调用即生效，无需重启；想恢复默认发 /model default。"
evidence: "2026-08-19 现场：绘画会话 880a62be model_used={pro:9, flash:3}，飞书会话 2a3385da model_override=flash；CLI --session 传 8 位前缀报[会话不存在]，补全 ID 后写入 pro 成功且持久化。"
tags: [model_override, 飞书, 模型切换, CLI, M50]
source: {}
status: active
created_at: "2026-08-19T12:26:20.340920+08:00"
updated_at: "2026-08-19T12:26:20.340920+08:00"
---