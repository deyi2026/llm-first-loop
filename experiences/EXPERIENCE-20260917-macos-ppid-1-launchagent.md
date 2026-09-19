---
title: macOS PPID=1 不等于孤儿进程，需先查 LaunchAgent
scenario: "macOS 128GB 机器排查内存占用与孤儿进程，多个 PPID=1 的 node/python 服务（vite :5174、openclaw gateway、hermes gateway、embedding_server）疑似孤儿"
root_cause: ""
solution: 先跑 launchctl list 对照 LaunchAgent 标签；用 lsof 查 LISTEN/ESTABLISHED 判定服务在用状态；确认为 launchd 受管后不 kill。僵尸进程通过重启其 GUI 父进程（MCP Console）清理。
evidence: execute_command 回执：`launchctl list` 显示 local.tdx-vite (PID 20055) 与 local.tdx-server (PID 10982)；kill 10993 后 ps -p 20055 显示 vite 11 秒内重生且 PPID=1；~/Library/LaunchAgents/local.tdx-vite.plist 存在；ps state=Z 的 5 个 defunct 进程 PPID 均为 54557 (MCP Console.app)。
tags: [macos, orphan-process, launchd, launchagent, memory, ops]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-17T23:18:50.575678+08:00"
updated_at: "2026-09-17T23:18:50.575678+08:00"
---

在 macOS 上排查孤儿进程时，PPID=1 不能作为孤儿判据：launchd LaunchAgent 服务（KeepAlive）的进程也直接挂在 launchd 下。正确顺序：先 `launchctl list` 对照服务名，再 `lsof -iTCP -sTCP:LISTEN` 查端口归属和 ESTABLISHED 连接判断是否在用，最后才考虑 kill。本次实例：PID 10993 vite (:5174, 18天, 0连接) kill 后 11 秒被 local.tdx-vite KeepAlive 重生，说明它是受管服务。僵尸进程(defunct)只能由父进程 wait() 回收，macOS 上常见于 GUI App（如 MCP Console）不 reap 子进程，唯一清理方式是重启该 GUI App。GUI App（Chrome/Safari/微信等）PPID=1 是 macOS 常态，不是孤儿。