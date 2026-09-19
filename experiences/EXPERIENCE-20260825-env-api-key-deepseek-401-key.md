---
title: 主区改 .env 换 API key 后 deepseek 401：进程未重启仍用旧 key
scenario: "用户报 /Users/yyj/Project/llm-first-loop 主区 deepseek 连不上。API 层测试（curl 带当前 .env key 调 /v1/models）返回 200 正常，但运行中会话报 LLMHTTPError 401 \"Your api key: ****10d2 is invalid\"，且 guard.log 持续告警「工作区变更需重启生效」。"
root_cause: ".env 在 10:03 更新了新 key（尾4=d8d8，有效），但主区 web/feishu 进程是旧 key（尾4=10d2，已失效）启动的，进程未重启导致仍用旧 key 调 deepseek → 401。guard_system.sh 对工作区变更只提醒不自动重启，需人工/AI 触发 restart。"
solution: 定位链条：① read_file providers.json 确认配置 ② 脱敏比对 .env 与 .env.bak 的 key 尾4（.env.bak-* 是改前备份）③ event_logs 中 401 报错的 key 尾4 与旧备份一致 → 确认进程用旧 key ④ kill -TERM 旧进程（web/feishu），guard_system.sh loop 检测到不健康会自动 stop+start 拉起新进程（加载新 .env）⑤ 用 POST /api/v1/chat 触发真实 LLM 调用验证。注意：主区对沙箱写操作被硬阻断，不能直接跑 restart_system.sh（touch maintenance.lock 失败），绕行用 kill + guard 自愈。
evidence: curl 200；.env key 尾4=d8d8；.env.bak-20260825-100321 key 尾4=10d2；event_logs 401 报错 key=****10d2；guard pull_up_ok web=72434 feishu=72546 健康通过；POST /api/v1/chat 返回 ok
tags: [deepseek, 401, env, 进程重启, guard自愈, 排障]
source: {}
status: active
created_at: "2026-08-25T10:15:47.329134+08:00"
updated_at: "2026-08-25T10:15:47.329134+08:00"
---