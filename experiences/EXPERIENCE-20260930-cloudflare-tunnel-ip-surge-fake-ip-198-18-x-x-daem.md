---
title: Cloudflare Tunnel 边缘 IP 被 Surge fake-IP(198.18.x.x) 污染：即使已绑物理网卡，重拨永不自愈，须重启 daemon
scenario: "本机（macOS+Surge）cloudflared named tunnel（launchd: com.llmfirstloop.cloudflared，--edge-bind-address 物理网卡）运行数日后边缘连接全掉、llmfirstloop.com 打不开，复发于 2026-09-30，与 EXPERIENCE-20260921 同源"
root_cause: ""
solution: "判据：daemon 日志出现 dial tcp <物理网卡>:0->198.18.18.x:7844 i/o timeout（198.18.x.x 为 Surge fake-IP 段）即锁定。修复：launchctl kickstart -k gui/$(id -u)/com.llmfirstloop.cloudflared，重启后重新解析边缘地址；验证 /ready readyConnections>0 且公网 303/200。注意 --edge-bind-address 绑物理网卡不能防此问题，因为污染发生在 DNS 解析出的目标 IP 本身。当前性验证：curl -s http://127.0.0.1:20243/ready 应得 readyConnections≥2。"
evidence: "evidence://v1/b249ea7461bad3347dfb8476a9fdd413e0b0ae4a0330e1bbbcc49bb1909e55b3; 公网探测 HTTP:530 error code:1033；metrics 20243 readyConnections:0；日志 198.18.18.x i/o timeout；kickstart 后 readyConnections:4、llmfirstloop.com 303→/login?next=/ui/v2/"
tags: [cloudflared, surge, fake-ip, named-tunnel, 1033]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-30T11:46:31.733465+08:00"
updated_at: "2026-09-30T11:46:31.733465+08:00"
---

公网 530/1033 + 本机 metrics readyConnections=0 + named 日志持续 "DialContext error: dial tcp 192.168.3.253:0->198.18.18.x:7844: i/o timeout" → 边缘地址被 Surge fake-IP DNS 污染（198.18.0.0/15），daemon 重试永不自愈。用 launchctl kickstart -k 干净重启即恢复（本次 8 秒内 4 连接，域名恢复 303→/login）。当前性验证：先 `tail -5 /Users/yyj/Project/llm-first-loop-mirror/data/cloudflared-named.log` 确认无 198.18.x timeout，再 `curl -s http://127.0.0.1:20243/ready` 应得 readyConnections≥2，最后 `curl -sI https://llmfirstloop.com/` 应得 303（非 530）。