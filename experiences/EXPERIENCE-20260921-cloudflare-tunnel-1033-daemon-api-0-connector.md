---
title: Cloudflare Tunnel 1033：daemon 显示已连接但 API 0 connector 时，重启并绑定物理网卡
scenario: 本机（macOS，有 Surge 代理）用 cloudflared Named Tunnel 把 llmfirstloop.com 暴露给公网；用户反馈域名打不开/无法进入登录页
root_cause: ""
solution: 判定链：本地 origin 健康 + ingress 正确 + 域名 530/1033 ⇒ 查 cloudflared tunnel info <tunnel-id> 是否有活跃 connector。daemon 本地 metrics 显示连接正常但 API 为 0 ⇒ 旧 daemon 边缘注册失效（代理干扰下反复重连）。修复：重启 daemon 并加 --protocol http2 --edge-bind-address <物理网卡IP>（参考同机健康隧道的启动参数）。防复发：把这组参数固化进 scripts/start-web-tunnel.sh，并考虑 launchd 托管。
evidence: "curl 修复前 530/1033、修复后 https://app.llmfirstloop.com/login 200（title: LLM First Loop · 登录）；cloudflared tunnel info a1cd626b 修复前\"does not have any active connection\"、修复后列出 2 个 CONNECTOR（sea07/08/10/11）；/private/tmp/tunnel-test.log 与 data/cloudflared-named.log 中的边缘掉线记录"
tags: [cloudflared, cloudflare-tunnel, error-1033, surge-proxy-interference, llmfirstloop.com, troubleshooting]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-21T11:43:32.746072+08:00"
updated_at: "2026-09-21T11:43:32.746072+08:00"
supersedes: [EXPERIENCE-20260819-llm-sub2api-dns-tls, EXPERIENCE-20260919-awesun-kickstart-root-daemon]
---

2026-09-21 用户报"域名登录不了"。事实链：curl https://app.llmfirstloop.com → 530 + error code 1033（Cloudflare tunnel unreachable）。本地 web 服务 127.0.0.1:8903 健康（303→/login）；tunnel ingress 配置正确。关键分叉：cloudflared tunnel info a1cd626b 显示 0 活跃连接，而本机 cloudflared daemon（3天 uptime）metrics 显示 4 连接且日志反复 Registered——边缘侧从未真正稳定注册（日志大量 TLS handshake EOF / connection with edge closed，几分钟一次）。同机另一隧道 mcp-console 的进程健康，参数带 --protocol http2 --edge-bind-address 192.168.3.x（绑物理网卡绕开 Surge 代理干扰）。处理：kill 旧 daemon，用同款参数重启（nohup cloudflared tunnel --no-autoupdate --config config.local.yaml --protocol http2 --edge-bind-address 192.168.3.x --metrics 127.0.0.1:20243 run）。结果：tunnel info 出现 connector，https://llmfirstloop.com/ → 303 → /login，app.llmfirstloop.com/login → 200。