---
title: AweSun 远程连不上：仅重启用户域进程不够，需 kickstart root 域两个 daemon
scenario: "macOS 向日葵(AweSun)客户端重启后仍无法远程连接；设备实际在线、密码校验通过，但会话卡死在 P2P 建连阶段。机器上有 Surge 增强模式(TUN, utun4 默认路由, 198.18.0.1)。"
root_cause: ""
solution: 必须把 root 域服务也重启：sudo launchctl kickstart -k system/com.oray.awesun.service 和 system/com.oray.awesun.helper（用户域的 com.oray.awesun.client.startup / desktopagent 已重启过仍不够）。重启后通过 /var/log/AweSun/awesun_service.log 确认 P2P_CONNECTED 与 UDP 监听端口。
evidence: "/var/log/AweSun/awesun_service.log 19:54:31/19:54:55 两次 express login 卡在 p2p connect；19:56 root 服务 kickstart 后 19:58:33 relay 建连、19:58:42 P2P_CONNECTED_0 error:0、UDP *:15608 活跃；lsof 确认会话通道"
tags: [awesun, oray, 远程桌面, macOS, launchctl, surge-tun, p2p]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-19T20:00:09.675959+08:00"
updated_at: "2026-09-19T20:00:09.675959+08:00"
---

现象：Mac 上向日葵(AweSun)远程连不上，仅重启用户域服务无效。诊断路径：1) sudo launchctl list | grep awesun 确认 root 域有 com.oray.awesun.service 和 com.oray.awesun.helper 两个 daemon；2) echo '密码' | sudo -S launchctl kickstart -k system/<label> 逐个重启；3) 看日志 /var/log/AweSun/awesun_service.log：设备注册在线(logon OK/client registered)但用户连接尝试停在 'connect ipv4 p2p server' 后无后续 = P2P 建连挂死；4) 重启 root 服务后日志出现 OnConnectRequest→OnConnectAck→P2P_CONNECTED_0 error:0，UDP *:15608 活跃 = 会话恢复。注意点：该机跑 Surge 增强模式(utun4 198.18.0.1 持默认路由)，P2P 打洞受其影响是脆弱点，若复发可先关 Surge 增强模式再测；Surge 未开 6171 HTTP API，只能菜单栏手动关。另：AweSun_Desktop 当日 11:49 有崩溃报告，重启桌面代理一并解决。