---
title: DoH 被阻断网络下 cloudflared 隧道自愈失败的诊断路径与修复验证
scenario: "本机(CST网络)收到 \"Tunnel 自愈重启失败: https://cloudflare-dns.com/dns-query: error sending request...\" 三条 DoH 报错，需判断隧道真实状态与重启可行性"
root_cause: ""
solution: "先分区检查：(1) 隧道本体 lsof -p <pid> 看 198.41.x:7844 ESTABLISHED、metrics :20242 ha_connections=4；(2) 公网 curl https://llmfirstloop.com/auth/status；(3) 诊断网络层：curl 1.1.1.1:443 与 cloudflare-dns.com 得 RST/timeout 而 ICMP 通 ⇒ DoH 阻断非断网；(4) 验证重启可行性用临时第二副本（同 config + 独立 --metrics 端口，20s 后 kill），看 DNS precheck 是否 PASS。注意 macOS 无 timeout 命令。"
evidence: "evidence://v1/e54a6fe86ddc6135e9aa223e3d89965dfd125686b972efcedfd3be4bad32a786 (tunnel log UTC 尾部); evidence://v1/09f8379a137fc41a052377f35a6675332a588272a1db277604e5c39cb64d54b6 (DoH 443 RST/超时+ICMP通); 测试副本输出 2026-09-17T22:55:04-08Z 4 连接注册+DNS precheck PASS"
tags: [cloudflared, tunnel, doh-blocked, network, launchd]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T06:55:59.533943+08:00"
updated_at: "2026-09-18T06:55:59.533943+08:00"
---

cloudflared 新实例启动时先用系统明文 DNS（/etc/resolv.conf: 223.5.5.5/119.29.29.29）解析 region1/region2.v2.argotunnel.com；失败才回退 DoH（cloudflare-dns/dns.google/dns.quad9）。本网络 443→DoH 全被 RST/超时阻断（ICMP 通、:7844 通），因此"系统 DNS 瞬断 + 需要重启"的组合必然复现该告警。已验证：系统 DNS 正常时新副本 4 秒注册满 4 连接（/tmp/tunnel-test.log, 2026-09-17T22:55Z）；运行中实例靠既有连接存活不受影响。排查要点：data/cloudflared-named.log 时间戳是 UTC；launchctl print gui/$(id -u)/com.llmfirstloop.cloudflared 看 runs/pid；metrics 127.0.0.1:20242 的 ha_connections。