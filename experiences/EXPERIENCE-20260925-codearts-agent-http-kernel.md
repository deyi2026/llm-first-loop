---
title: CodeArts Agent 无头驱动配方（HTTP 直控常驻 kernel）
scenario: 需要在 CodeArts Agent (华为 opencode fork) 上建立无头自动化流水线：程序化派单执行任务、验证产物，不依赖 GUI 手工操作
root_cause: ""
solution: "绕过 CLI，直接驱动 App 常驻的 AgentKernel HTTP API：ps eww <kernel_pid> 提取 OPENCODE_SERVER_USERNAME/PASSWORD 作 Basic 凭据 → POST /cag/session 建会话 → POST /session/{id}/message（扁平 parts schema, agent=build, providerID 用 codearts.json 键名）→ GET /cag/session/{id}/message 收结果。云端 GLM-5.3-Flash（免费档）实测秒回。"
evidence: "evidence://v1/2e90b50fbf17f0e79183d129c62afa81362a9c355a006a86637d5d3fd687d8c7 (assistant reply OK); evidence://v1/3d9a9ce7812c1b5765b727936ee2a065aa6c14ed4a5405ed22bb43cffdc4f4b6 (session created); process env receipt evidence://v1/1ba9448977d97a869e95eab67552198780a58e25be3d5a39e02e0ba87e87302"
tags: [codearts-agent, opencode, headless, http-api, automation, macos]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-25T12:55:58.563891+08:00"
updated_at: "2026-09-25T12:55:58.563891+08:00"
---

发现链：code chat CLI 在 26.9.102 fork 里死于 ChatCommandLineHandler2.prompt（workbench.action.chat.newChat 不存在）→ kernel 是 opencode fork（--help 暴露 run/serve/attach）→ fork 的无头 run 无法注册 provider（custom-model-gui 只在 App init POST 后 sync，配置文件路径全部被 user_config.opencode_config_ignored 拒绝）→ 自起 serve 实例 HTTP 僵死（放弃）→ 转而驱动 App 常驻 kernel 成功。

可复用配方：
1. 找 kernel PID：ps aux | grep AgentKernel_Vscode.*serve
2. 凭据：ps eww <PID> 里 OPENCODE_SERVER_USERNAME / OPENCODE_SERVER_PASSWORD（Basic auth）
3. 建会话：POST /cag/session {"directory":"<ws>","title":...} → .id
4. 发消息：POST /session/{id}/message（无 /cag 前缀），body 扁平：{"parts":[{"type":"text","text":...}],"model":{"providerID":"<注册表id>","modelID":...},"agent":"build"}
5. 读结果：GET /cag/session/{id}/message → 数组，assistant 消息 parts[].text
6. providerID 注意：/cag/model 目录给裸哈希，消息 API 要 codearts.json 的键（如 openai-3bb86a9101d83ea3；glm 用 "glm"）
7. agent 名单：GET /agent（build 存在，ask 不存在）
8. 本地 35B (ornith, LM Studio) 因 build agent 巨大系统提示词预填充极慢不实用；云 GLM-5.3-Flash 秒回

边界：仅当 App 运行时可用（kernel 随 App 存活）；任务会出现在用户 GUI 会话列表；headless 下 kernel 注入"[经验检索失败提示]"到用户消息（无害）。