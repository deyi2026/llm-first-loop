---
title: cloudflared 1033 复发三连：修复要落真实入口(launchd plist)，毒地址池零连接死锁需重启+watchdog 自愈
scenario: "macOS + Surge(TUN/假IP) 环境下 cloudflared named tunnel 周期性 1033/530，域名无法登录；且\"验证通过后数小时复发\"、进程存活但零边缘连接"
root_cause: cloudflared 边缘地址池进程内缓存 + 修复落盘位置错位（脚本 vs launchd plist 真实入口）
solution: ①修复必须落到真实运行入口：launchctl print 确认服务存在，plist 才是权威，改脚本无效（脚本遇 launchd 托管会跳过）；②ha_connections=0 死锁靠重启进程清边缘地址池，不能等它自愈；③收敛单实例防双 connector；④上 watchdog（每 2min 查 metrics，连续 2 次 0 连接即 kickstart -k）；⑤验证标准=metrics ha≥1 + 域名 curl 200，缺一不可。
evidence: "2026-09-21T17:10 本机：修复后 metrics ha_connections=4 (lax01/lax10/lax08)，https://app.llmfirstloop.com/login 连续 8/8=200，root=303；watchdog LaunchAgent 已加载并试运行；plist 经 plutil -lint OK。死锁证据：data/cloudflared-named.log 17:00-17:06Z 持续 dial 198.18.18.47/27 i/o timeout 而 dscacheutil 同期返回真实 198.41.192.x。"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-21T17:12:36.443185+08:00"
updated_at: "2026-09-21T17:12:36.443185+08:00"
---

完整因果链（2026-09-21 三次 1033 事故复盘）：
1) 表层：530/1033，本地源站 200，cloudflared 进程存活。
2) 中层：daemon 内存边缘地址池被 Surge 假IP(198.18.x) 污染后，DNS 恢复干净也不会自愈——进程无限重拨假 IP（日志特征 "dial tcp ...->198.18.18.x:7844: i/o timeout" + "no free edge addresses left"），唯一恢复手段是重启进程。
3) 深层（为什么修了又坏）：修复参数只写进了 scripts/start-web-tunnel.sh，但脚本遇 launchd 托管会跳过；真正长期运行入口是 ~/Library/LaunchAgents/com.llmfirstloop.cloudflared.plist（KeepAlive），裸参数持续复活旧配置。另存在双 connector 并跑（手动+launchd）互相放大。
验证方法：metrics(127.0.0.1:20243) 的 cloudflared_tunnel_ha_connections 必须 ≥1，login curl 必须 200；dig 与系统解析器(dscacheutil)结果可能不一致，须分别核。
修复：bootout → PlistBuddy 补 --protocol http2 --edge-bind-address <en0-ip> --metrics 127.0.0.1:20243 → bootstrap；杀手动实例收敛为单 connector。
防复发：scripts/tunnel-watchdog.sh + LaunchAgent(StartInterval=120)，连续 2 次 ha_connections=0 即 kickstart -k，日志 data/tunnel-watchdog.log。
残留风险：Surge 假IP再发作时连接仍会断，但 ≤4 分钟内 watchdog 重启进程重新解析恢复；若 en0 DHCP 换 IP，plist 里硬编码的 192.168.3.253 需同步更新。