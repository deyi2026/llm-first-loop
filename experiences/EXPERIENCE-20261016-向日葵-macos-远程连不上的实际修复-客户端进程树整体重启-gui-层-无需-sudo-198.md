---
title: 向日葵(macOS)远程连不上的实际修复=客户端进程树整体重启（GUI 层，无需 sudo）；198.18 fake-IP 是常态而非元凶
scenario: "macOS 上向日葵(AweSun)远程控制反复连不上；此前已排查过 Surge 路由排除、/32 规则，均未解决。2026-10-16 19:32 用户确认在客户端进程树整体重启后连接成功。"
root_cause: ""
solution: |
  有效修复：只重启 GUI 层客户端进程树即可，无需 sudo、不需重启系统。
  
  1) 要重启的三类进程（2026-10-16 实测 PID 变化）：
     - 主客户端 AweSun：86211 → 58552
     - desktopagent：→ 58567
     - root 身份 AweSun 进程：87933（已陈旧约 20h）→ 58569
     注意：root 实例是由客户端自身拉起的，终止主客户端后它会随之退出并被重新拉起到新 PID —— 这是本次成功的关键，前几轮只重启主客户端而 root 实例仍驻留是无效重启。
  2) AweSun_Helper -m server（PID 87932，LaunchDaemon+KeepAlive）**不必**重启：它在本次连接成功的状态下仍是旧实例，所以它不是本次故障点；真要重启才需要 sudo。
  3) 198.18.0.1（Surge fake-IP 段）不是元凶：故障态与修复后连接成功态中，向日葵的对外连接源地址同样是 198.18.0.1，经 TUN 不影响连通。这是观察到的常态，不是每次都要追查的异常。
  4) 判断连通以用户侧端到端连接成功为准（2026-10-16 19:32 用户回报"已经连上了"）。日志层 p2p0 bind 成功只能作为辅助。
  5) 未验证/待定：Surge 里那条 `113.84.128.249/32` 的 tun-excluded-routes 是否必要，本次未做对照实验，不能断言它的作用。
evidence: "2026-10-16 重启后 ps 显示新 PID 58552/58567/58569（root 实例亦换新），新进程 TCP 均为 198.18.0.1:xxxx -> 对端 443 ESTABLISHED；AweSun_Helper 仍为 87932 未重启。用户 2026-10-16 19:32 回报连接成功。"
tags: [macos, 向日葵, awesun, 远程, 重启, fake-ip]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-16T19:32:36.334306+08:00"
updated_at: "2026-10-16T19:32:36.334306+08:00"
---