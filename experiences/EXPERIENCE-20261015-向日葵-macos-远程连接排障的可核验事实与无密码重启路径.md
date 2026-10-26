---
title: 向日葵(macOS)远程连接排障的可核验事实与无密码重启路径
scenario: macOS 上向日葵(AweSun)远程控制连不上，需要判断故障层次（客户端进程 / 网络出口 / 服务端），以及在不带 sudo 的情况下重启客户端。
root_cause: ""
solution: |
  可核验事实（本次实测）：
  1) 进程分两层：普通用户态实例 + root 特权实例(AweSun_Helper)。两者都由客户端自身拉起(root 实例 pid 以 root 运行)，因此**重启只需终止/重启用户态实例即可，无需 sudo**；只有手动去杀 root 实例才需密码。
  2) 判定"是否进入 P2P 直连"看日志三连：`Bind a p2p0(ipv4) stream` → `P2P_CONNECTED_0(KCP OR UDX), error: 0` → `change mode to p2p0(ipv4)`。只看到 `connect p2p server <ip>:4118 OK` / `login OK` 不代表打洞成功；随后若出现 `FWD_DISCONNECT_4(TCP)` / `fw4 disconnect`，通常只是切换到 P2P 后关闭转发通道的正常收尾，不是故障。
  3) local ip 落在 198.18.0.0/15 说明流量经 Surge TUN(fake-ip 段)，但**经 TUN ≠ P2P 被打断**：本次在经 Surge 的情况下 p2p 打洞仍成功。故不能仅凭 fake-ip 就断定"代理软件干扰 P2P"。
  4) 日志路径：/private/var/log/AweSun/awesun_service.log（awesun_service 相关进程与网络状态均落此文件）。
  
  方法论：判断"根因是否在客户端进程层"，最直接的证据是日志里 p2p0 通道是否 bind 成功，而不是先怀疑代理/网络。
evidence: "日志(2026-10-15)：19:32:50 `connect p2p server 113.105.147.112:4118 OK`+`login OK`，local ip 198.18.0.1:15620；19:33:06-19:33:17 `punch ports begin/end`；19:33:17 `Bind a p2p0(ipv4) stream`、`P2P_CONNECTED_0(KCP OR UDX), error: 0`、`change mode to p2p0(ipv4)`；19:34:41 `FWD_DISCONNECT_4(TCP)`。对比 19:27/13:15 两次：连到 :4118 即断，从无 p2p0 bind。"
tags: [macos, 向日葵, awesun, p2p, 排障, surge, sudo]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-15T19:39:41.817962+08:00"
updated_at: "2026-10-15T19:39:41.817962+08:00"
supersedes: [EXPERIENCE-20261015-向日葵-macos-远程连不上-真实日志在-var-log-awesun-library-下的是旧档]
---