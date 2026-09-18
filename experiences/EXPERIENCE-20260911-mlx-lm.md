---
title: mlx-lm 底座本地模型服务的便捷启停方案与沙箱陷阱
scenario: 在只读仓库/沙箱环境下，为本地 mlx_lm 服务器（ornith-1.5-35b 与 qwen3.8-27b 共用 8901 端口）编写统一 start/stop/status/smoke/logs 控制脚本
root_cause: ""
solution: 脚本放 /tmp 开发实测，让用户 cp 进仓库 scripts/；启动用 python 双 fork+setsid 脱离会话；进程信息用 lsof/pgrep 替代被沙箱禁用的 ps；smoke 回退 reasoning_content
evidence: "/tmp/llm8901.sh（双模型 stop/start/smoke/status 四轮实测通过，qwen 修复前 ModuleNotFoundError、修复后 smoke:2）；/tmp/llm8901-lifecycle{,2,3,4}.log"
tags: [mlx_lm, macos, daemonize, launchd, sandbox]
source: {}
status: active
created_at: "2026-09-11T03:37:08.224965+08:00"
updated_at: "2026-09-11T03:37:08.224965+08:00"
---

基于 /Users/yyj/Project/research/mlx-lm 底座（integration/qwen-cache-continuity-20260908 分支，cognitive prompt cache）总结的 8901 端口本地模型控制要点：1) mlx_lm 未 pip 安装，必须以仓库根为 cwd 运行 `python -m mlx_lm.server`，否则 ModuleNotFoundError；底座 scripts/start-ornith-server.sh 自带 cd，launchd 用 WorkingDirectory，自写脚本要在 daemonize 后 os.chdir(BASE)。2) macOS 进程脱离会话用 Python 双 fork+setsid（无 setsid(1)），验证 PPID=1 可用 `pgrep -P 1 -l`。3) thinking 模型（ornith native / qwen thinking）smoke 时 content 可能为 None，需回退 reasoning_content 且 max_tokens 给到 64。4) 沙箱限制：仓库与 ~/Library/LaunchAgents 只读、/bin/ps 被 Operation not permitted 挡（用 lsof/pgrep 替代）、/tmp 是符号链接（edit_file 拒绝，须用 /private/tmp 或 shell）。5) curl 一律加 --max-time，否则 60s 工具超时先于慢请求完成。