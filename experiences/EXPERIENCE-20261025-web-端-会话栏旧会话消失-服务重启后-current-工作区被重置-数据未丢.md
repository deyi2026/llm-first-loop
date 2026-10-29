---
title: "web 端\"会话栏旧会话消失\"= 服务重启后 current 工作区被重置（数据未丢）"
scenario: "LFL web 端（uvicorn :8903，src/llm_loop/web/routes.py）会话栏只显示\"当前工作区\"的会话（GET /api/v1/sessions → engine 所在工作区目录 data/sessions/<workspace-id>/）。web 服务重启（service_control restart，本次 2026-10-25 22:29 主区 llm-first-loop 目录被移除、服务从 llm-first-loop-mirror 启动，generation 319）后，workspaces.json 的 current 重置为启动目录 mirror（仅 10 个会话），用户之前所在的 research 工作区（100 个会话）不再显示，浏览器记住的旧 session 请求从 200 变 404，表象为\"之前的会话全部不见了\"。"
root_cause: ""
solution: 不要按数据丢失处理。先核 data/workspaces.json 的 current 与 data/sessions/<workspace-id>/ 目录内容，再 grep data/web.log 中旧 session_id 的 200/404 分界。恢复：web UI 工作区切换器（POST /api/v1/workspaces/switch）切回原工作区即可，无需动数据；若有会话运行中会返回 409 workspace_busy，等运行结束再切。注意：switch 会同时切换会话列表/工具根/文件预览根，是全局状态，不要在有运行中会话时替用户切换。
evidence: "web.log: 0991556a 重启前 200×3018 / 重启后 404；workspaces.json current=--Users-<user>-Project-llm-first-loop-mirror--；sessions/--Users-<user>-Project-research--/0991556a-eab1-4a63-9113-ea54a5166bf4.json 存在；restart-receipt.json 22:29:38 generation 319"
tags: [web, webui, sessions, workspace, restart, service_control]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-25T22:42:58.497154+08:00"
updated_at: "2026-10-25T22:42:58.497154+08:00"
---

排查路径：1) ls data/sessions/ 按工作区目录核对会话文件数（--Users-<user>-lfl-workspace-- 5435 个、--Users-<user>-Project-research-- 100 个均在）；2) grep data/web.log 中浏览器记住的旧 session_id：重启前 200 OK（3018 次）→ 重启后 404 Not Found，即数据没丢、是 current 工作区变了；3) data/workspaces.json 的 current 字段被重置为 web 启动目录（mirror）。修复：web UI 工作区选择器切回原工作区即可恢复；有运行中会话时 switch 返回 409，需等会话结束。