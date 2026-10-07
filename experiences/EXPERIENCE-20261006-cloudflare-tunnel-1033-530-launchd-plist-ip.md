---
title: Cloudflare Tunnel 公网 1033/530：launchd plist 硬编码旧内网 IP 导致边缘连接全失
scenario: Mac 换网络后，Cloudflare Named Tunnel 域名公网 530/1033，但本地服务和进程看起来都正常；launchd 托管的 cloudflared 进程存活却被 CF 判定 0 连接。
root_cause: ""
solution: "1) CF API /accounts/{acct}/tunnels 查各隧道 conns 数定位断的是哪条隧道；2) 查 dns_records CNAME 确认域名→隧道映射；3) ps 看 cloudflared 启动参数是否含 --edge-bind-address 旧 IP；4) ipconfig getifaddr en0 取新 IP 改 plist；5) launchctl bootout + bootstrap 重载（kickstart -k 不重读 plist）；6) 用隧道 API conns + 公网 curl 双重验证。长期方案：plist 不 pin IP，改用 wrapper 脚本动态取当前 IP 启动。"
evidence: "CF API tunnels conns=0→2；https://mcp.llmfirstloop.com/health 530/1033→200；oauth-protected-resource 200；launchd plist 192.168.3.170→192.168.43.187 后 cloudflared-named.log 注册 sea09/sea11 两条边缘连接；会话内 execute_command/playwright 回执齐备。"
tags: [cloudflared, launchd, edge-bind-address, fake-ip-vpn, mcp-console, tunnel-1033]
source:
  config: /Users/yyj/Project/llm-first-loop-mirror/cloudflared/config.local.yaml
  plist: /Users/yyj/Library/LaunchAgents/com.llmfirstloop.cloudflared.plist
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-06T20:57:00.455937+08:00"
updated_at: "2026-10-06T20:57:00.455937+08:00"
---

排查链：用户报 "MCP用不了 127.0.0.1:8790"。本地 /health、/api/status、tunnel 均 ok → playwright 打开控制台 UI 看到 "Tun err" → 公网 https://mcp.llmfirstloop.com 返回 530/1033 → CF API：llmfirstloop-web 隧道 conns=0，而 mcp-console 隧道 conns=2 → DNS mcp.llmfirstloop.com CNAME 指向 llmfirstloop-web（2026-09-23 有意切换，见 config.local.yaml 注释：MCP Console 自带隧道 disableChunkedEncoding 破坏 ChatGPT OAuth DCR）→ 该隧道由 ~/Library/LaunchAgents/com.llmfirstloop.cloudflared.plist 托管，plist 硬编码 --edge-bind-address 192.168.3.170（旧网段），本机已换到 192.168.43.x，进程活着但边缘连接全死。修复：ipconfig getifaddr en0 取当前 IP，sed 替换 plist，launchctl bootout+bootstrap（注意 kickstart -k 不会重读 plist，改参数必须 bootout+bootstrap；bootstrap 偶发 5: Input/output error，重试即成功）。验证：CF API conns=2 + 公网 /health 200 + oauth-protected-resource 200。遗留隐患：IP 仍是静态 pin，换网络/换 Wi-Fi 会复发；mcp.toml 中 tunnelCfApiToken(cfut_) 已失效(Invalid access token)，旧 cfat_ 仍可用。