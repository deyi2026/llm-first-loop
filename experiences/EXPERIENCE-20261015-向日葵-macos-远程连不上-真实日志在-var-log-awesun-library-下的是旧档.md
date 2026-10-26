---
title: 向日葵 macOS 远程连不上：真实日志在 /var/log/AweSun，~/Library 下的是旧档
scenario: "macOS 上 AweSun（向日葵）客户端进程在跑，但远端连不上。排查\"是否已上线\"。"
root_cause: ""
solution: "当前性验证：先执行 `ls -lt /var/log/AweSun/ | head` 确认当前活跃日志（今天应有 shell.log / awesun_service.log mtime 为当前时刻）；若目录不存在或无当日文件，先 `ls -d /var/log/AweSun ~/Library/'Application Support'/AweSun/log` 确认路径，再 `grep -c 'received express login' /var/log/AweSun/awesun_service.log`（无匹配返回 1 属正常，用 || true 保护，fail_fast 会中断管道）。判定在线用 shell.log 的 `isOnline: true`；判定远端请求是否到达用 awesun_service.log 的 `received express login`；判定建链失败用 `mdesktop discard data control` / `keepalive timeout` / `udpstack connect timeout`。对比重启时间点前后是否同样症状，可判定重启是否有效（本例 13:15 已有 discard，19:26 重启无效，故障在网络层而非客户端进程）。"
evidence: "本机实测 2026-10-15：/var/log/AweSun/awesun_service.log 出现 19:27:07、19:27:36、19:28:17、19:29:29 四次 `received express login`→`Check password: type(0), account(yyj)`→`connect ipv4 p2p server @ 14.152.91.5:4118`，无后续会话；13:09~15:38 区间 `mdesktop discard data control(3..6)`。~/Library/Application Support/AweSun/log/shell.log mtime 为 2026-03-31，非当前日志。"
tags: [awesun, sunlogin, macos, 远程, 日志定位, 排障]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-15T19:30:30.178673+08:00"
updated_at: "2026-10-15T19:30:30.178673+08:00"
---