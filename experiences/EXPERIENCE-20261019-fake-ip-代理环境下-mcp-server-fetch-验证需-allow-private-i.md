---
title: fake-ip 代理环境下 mcp-server-fetch 验证需 --allow-private-ips
scenario: 本机 fake-ip 代理环境（域名解析到 198.18.x.x）下验证 uvx mcp-server-fetch 接入 LFL MCP 文件配置层
root_cause: ""
solution: "配置 mcp-server-fetch 时按环境加 --allow-private-ips 参数；验证断言用 [状态: success] 前缀或显式内容特征，不用目标域名子串做弱断言。复现：uvx mcp-server-fetch --help 2>&1 | grep allow-private-ips 应有输出。"
evidence: "execute_command 回执（2026-10-19）：同一 .mcp.json 仅差 --allow-private-ips 参数，第一次 CALL 返回 \"[状态: failure] ... Refused to fetch https://example.com/robots.txt: example.com resolves to 198.18.13.64, which is not a public address\"，加参数后返回 \"[状态: success] Contents of https://example.com/: This domain is for use in documentation examples...\"；两次 PLAN/ASSEMBLED 均成功（file@workspace, ['mcp_fetch_fetch','mcp_prompt_get']）"
tags: [mcp, verification, network, fake-ip, uvx]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-19T00:28:11.829796+08:00"
updated_at: "2026-10-19T00:28:11.829796+08:00"
---

端到端验证 MCP stdio 接入时：uvx mcp-server-fetch 默认拒绝抓取解析到 198.18.0.0/15（fake-ip 段）的域名，报 "resolves to X, which is not a public address"。这不是客户端问题，是 server 侧 SSRF 防护 + 本机代理 fake-ip 模式的交互。验证脚本需把 mcpServers.fetch.args 加 --allow-private-ips 才能走通成功路径；同时注意弱断言陷阱：错误信息里含目标域名会让 "example" in text.lower() 类断言假通过，应断言成功状态标记而非域名子串。
当前性验证：uvx mcp-server-fetch --help 列出 --allow-private-ips 选项仍存在；dig +short example.com 若返回 198.18.x.x 说明 fake-ip 环境仍在，结论适用。