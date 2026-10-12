---
title: MCP Console 8790 静默死亡后的重启解锁流程（孤儿 helper + 陈旧锁双重阻断）
scenario: "macOS 本机 MCP Console.app（127.0.0.1:8790，公网 mcp.llmfirstloop.com 经 cloudflared Named Tunnel）在 tunnel 停止/重启循环后静默死亡（无 .ips、无关闭日志），且 open -a 无法拉起"
root_cause: ""
solution: "三步解锁：pkill -f \"MCP Console.app/Contents/MacOS\"（孤儿 helper 挡住 LaunchServices 单实例检测）→ rm ~/.mcp-console/desktop-{instance,profile}.lock（陈旧 pid 锁）→ open -a \"MCP Console\"，约 10 秒后 8790 恢复。判定存活用 POST /mcp 看 411（无 Content-Length 拒绝）而非 200。"
evidence: "sidecar-console.log 止于 2026-10-04T13:27:34Z tunnel 重启循环后；bootstrap log epoch 1791121219818 重启成功；/tmp/mcp-watch.log 21:40:49 起 local=411 pub=411"
tags: [mcp-console, macos, launchd, cloudflared, restart, stale-lock]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-04T21:41:42.588061+08:00"
updated_at: "2026-10-04T21:41:42.588061+08:00"
---

症状：watcher 探测 http://127.0.0.1:8790/mcp 返回 000（连接拒绝），公网 https://mcp.llmfirstloop.com/mcp 502；ps 无 mcp-console 主进程。诊断链：8790 归属 MCP Console.app（Rust，embedded 模式，主进程 spawn 内嵌 sidecar）；sidecar 日志 ~/.mcp-console/data/sidecar-console.log 停止时间=死亡时间；desktop-bootstrap.log 的 [desktop:start]/[desktop:health] 行确认启动与就绪；崩溃家族见 docs/mcp-console-crash-report-v0.1.411.md（SIGABRT 与 cloudflared 停止/重启循环强相关）。修复：pkill -f "MCP Console.app/Contents/MacOS" 清掉孤儿 helper（它会骗过 LaunchServices 使 open -a 静默 no-op）→ 删 ~/.mcp-console/desktop-instance.lock 与 desktop-profile.lock → open -a "MCP Console" → ~10s 后恢复。注意 411（POST 无 Content-Length）= 存活签名，不是故障。当前性验证：curl -sS -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8790/mcp 应得 411，且 ps aux | grep "MacOS/mcp-console" 应见主进程。