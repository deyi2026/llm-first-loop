---
title: DHCP IP 漂移导致 cloudflared named tunnel 530：plist edge-bind-address 失效的修复
scenario: "本机（macOS + Surge）访问 https://llmfirstloop.com 报连不上/530；web 服务本身与 cloudflared 进程均存活"
root_cause: ""
solution: 查 cloudflared-named.log 的 bind 错误确认 edge-bind-address IP 失效 → 改 plist → bootout+bootstrap 重载（kickstart 不重读 plist）→ 验证 /ready=200、ha_connections≥1、域名 200
evidence: "execute_command 回执：cloudflared-named.log \"bind: can't assign requested address\"（192.168.3.x）；bootout+bootstrap 后 /ready {\"status\":200,\"readyConnections\":2}、ha_connections=2；curl https://llmfirstloop.com/login?next=... → http_code=200"
tags: [cloudflared, launchd, DHCP, 530, tunnel]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-01T16:56:43.177162+08:00"
updated_at: "2026-10-01T16:56:43.177162+08:00"
---

症状：https://llmfirstloop.com 返回 530（Cloudflare 无存活连接器）。诊断链：① 本地 web (127.0.0.1:8903) curl 正常排除服务；② 域名 DNS 走 Surge fake-IP (198.18.x)，实为 cloudflared named tunnel 入口；③ 隧道进程活着但 metrics ha_connections=0、/ready 503；④ cloudflared-named.log 报 "dial tcp 192.168.3.x:0->...: bind: can't assign requested address"——DHCP 把本机 IP 换成 192.168.3.x，plist 写死的 --edge-bind-address 失效。修复：sed 改 ~/Library/LaunchAgents/com.llmfirstloop.cloudflared.plist 的 IP（先备份 .bak-20261001-ipfix），必须 launchctl bootout + bootstrap 重载——kickstart 用 launchd 缓存的旧 job 定义不重读 plist，改了也白改。验证 /ready readyConnections=2 + 域名 curl 200。注意：scripts/tunnel-watchdog.sh 只 kickstart 进程，不能修 plist IP，此场景下会无限无效重启；根治靠路由器 DHCP 静态绑定本机 IP。