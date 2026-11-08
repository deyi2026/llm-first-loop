---
title: 跨会话唤醒：用 lfl --session 注入消息叫起无 run 的离线会话，必须显式 --workspace
scenario: 协作方会话（如 0a79bf7c）没有活跃 run 时，help_request 落盘的请求永远不会被读到（help_inbox 纯拉取式，无注入点）。需要在不重启服务、不伪造用户身份的前提下，让该会话启动一个 run 读到收件箱并收口自己名下阻塞他人的 lane。
root_cause: CLI 单次运行是唯一能把 user message 追加进指定会话并触发 run 的官方入口（cli.py 旧 main 的 --session/--message-file）。默认 workspace 解析会落到 .releases/<hash> 安装目录（lfl paths 显示 LFL_WORKSPACE_ROOT=.releases/460e69fd...），而会话按 workspace 编码分目录存放（data/sessions/--Users-operator-Project-llm-first-loop-mirror--/），因此不加 --workspace 时 SessionStore.exists() 查错目录，报 Session not found。
solution: |
  1) 先取完整 session_id（data/sessions/*/ 目录下的 json 文件名）。2) 确认无活跃 run 占用：lsof <session>.run.lock 无输出、ps 无对应 launch 进程。3) 消息先落盘（RULE-AI-36），明确标注"由某会话在用户某时授权下注入，非用户本人发言"，并写清请求、边界（不要动谁的 lane、不要 push、不要改产品代码）。4) 命令必须显式带 --workspace：`lfl --workspace <repo_root> --session <id> --message-file <file> --output text --no-stream`，后台执行。5) 用 job_output 取最终答复，再独立核验对方自述（lane 账本 status/version、事件日志、补丁 sha256、help_inbox pending 计数）。
  当前性验证：先跑 `.venv/bin/lfl paths | grep LFL_WORKSPACE_ROOT` 确认默认 workspace 是否仍落到 .releases/<hash>，并 `ls data/sessions/--<workspace编码>--/<session_id>.json` 确认会话仍按 workspace 分目录；若已改为全局 session 索引，则 --workspace 可能不再必需，需重新实测。
evidence: "首次不加 --workspace：exit=1 \"Session not found\"（job-287f9602c01b46d1a56a）；加 --workspace $HOME/Project/llm-first-loop-mirror 后同一命令 exit=0，14 轮 / 586232 tokens（job-7021daad25df427b8ca6）。会话 0a79bf7c 消息数 600→619；lane-372cd457→closed v4、lane-a147e3cd→closed v2；help_resolve(997fe96617a4)=resolved；PARKED-v0.3-P2.diff sha256 edfd6ad5bc2f2a2bfc2a0f16b197912032f6bb6cd566f95aa6d855bf5b41844c 实测匹配。"
tags: [cross-session, session-wake, cli, coordination, workspace-resolution, lane-blocking]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-08T10:00:20.266163+08:00"
updated_at: "2026-11-08T10:00:20.266163+08:00"
supersedes: [EXPERIENCE-20261025-web-端-会话栏旧会话消失-服务重启后-current-工作区被重置-数据未丢, EXPERIENCE-20261029-lfl-三服务并发启动撞-runtime-manifest-json-tmp-固定名竞态-启动即崩]
---