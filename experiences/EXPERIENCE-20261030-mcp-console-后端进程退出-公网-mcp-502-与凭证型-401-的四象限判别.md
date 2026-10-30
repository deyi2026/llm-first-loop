---
title: MCP Console 后端进程退出 → 公网 MCP 502：与凭证型 401 的四象限判别
scenario: "ChatGPT/远程客户端连 https://mcp.llmfirstloop.com/mcp 报“尚未连接成功 / server_info 工具调用内部失败”，cloudflared 隧道进程存活但公网返回 502。"
root_cause: "MCP Console 桌面主进程与 sidecar 已退出，127.0.0.1:8790 无监听（curl 000）；内置/独立 cloudflared 仍指向 8790，Cloudflare 回源失败返回 502。不是 token 过期（凭证问题应为 401），也不是 MCP 协议层问题。"
solution: |
  先做四象限判别，再动手：
  1) curl 127.0.0.1:8790/mcp 与 https://mcp.llmfirstloop.com/mcp 各取一次状态码；
  2) local=000 + pub=502 → 本机服务没起（本次）：重启 MCP Console.app（open -a "MCP Console"），等 10-15s；
  3) local=401 + pub=502 → 回源/隧道问题，查 cloudflared；
  4) 两侧均 401 → 链路与服务正常，问题在凭证/ChatGPT Connector；
  5) 恢复判据：local 与 pub 同步返回 401（无 token），带 channel token 的 tools/list 返回 200 且含 server_info。
  辅证：~/.mcp-console/data/server.lock 记录 pid，kill -0 判活；/tmp/mcp-watch.log 看 local/pub 历史状态；两条隧道时 200 只证明“至少一条通”，需分别看 metrics。
evidence: "2026-10-30T23:36-23:37 实测：netstat 无 127.0.0.1.8790 LISTEN、curl 8790 返回 000；公网 /mcp 返回 502（server: cloudflare, cf-ray）；cloudflared metrics 127.0.0.1:20243 显示 ha_connections=4 且 status_code 503 计数 20；server.lock pid=2836/desktop pid=2814 均 kill -0 DEAD；/tmp/mcp-watch.log 显示 23:31:00-23:31:21 local=411/pub=411（服务曾短暂在线）后 23:31:42 起持续 local=000/pub=502。"
tags: [mcp, chatgpt-connector, cloudflared, 502, diagnosis, mcp-console]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T23:38:54.506638+08:00"
updated_at: "2026-10-30T23:38:54.506638+08:00"
supersedes: [EXPERIENCE-20261013-公网-mcp-tool-failed-internally-三步判别-链路-服务-凭证分离定位]
---