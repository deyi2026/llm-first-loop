---
method_id: connect-then-drop-correlate-session-type-with-capture-log-a9bd53cdf7a1
name: connect-then-drop-correlate-session-type-with-capture-log
description: Linux 被控端远程控制/屏幕共享工具（向日葵/ToDesk/TeamViewer 类）报"连不上"，但服务进程在跑、厂商服务器探测可达时，先用连接历史把症状二分：有成对"开始桌面控制→十几秒后结束"记录即"连上即断"，故障在抓屏/渲染层而非网络层。再用 loginctl 会话 Type（wayland/x11）对齐工具自身抓屏日志同时间戳的 X11 报错（XOpenDisplay :0 failed），显示协议不匹配即为根因。修复走切换到 X11 会话（先确认 /usr/share/xsessions 存在对应会话与 Exec 二进制）或换支持 Wayland（pipewire）抓屏的工具；无 sudo 时把会话切换明确交还用户手动执行，不要尝试远程代切。
aliases: 向日葵连上就断, linux 远控一连上就掉线, todesk wayland 连不上, 远程桌面连上几秒就断开, 深度系统 远程控制 抓屏失败
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1204:80149ed77badba25c699
evidence_refs: learning:learn:3f795d177100
created_at: 2026-10-29T13:49:36.532524+08:00
updated_at: 2026-10-29T13:49:36.532524+08:00
---
## Trigger
Linux 被控端上远程控制/屏幕共享工具表现为"连不上"或"一连上就断"，但服务进程运行中、到厂商服务端网络探测正常；或连接/历史日志已出现"开始会话→数十秒内结束"的成对记录

## Discriminator
三条证据的时间戳对齐：①连接历史中成对的"开始桌面控制/结束桌面控制"记录（证明连接层 OK，区别于从未连上）；②当前图形会话 loginctl Type=wayland；③工具抓屏日志在连接尝试时刻报 X11 接口失败（如 XOpenDisplay :0 failed）。三者对齐即可锁定显示协议不匹配，排除网络/服务/账号层

## Short path
- 一次批量确认服务进程在跑 + 厂商服务器探测可达，同时排除服务与网络层
- 读连接/历史日志，按是否出现成对"开始/结束"记录判定是"连上即断"还是"从未连上"——后者转网络/账号分支，本路径停止
- 查当前图形会话类型（loginctl show-session 的 Type）与工具最新抓屏日志，按失败时间戳对齐错误（XOpenDisplay/X11 接口失败）
- 协议不匹配坐实后，检查 /usr/share/xsessions 有无可切换的 X11 会话且其 Exec 二进制存在；核实有无 sudo/root 权限远程切换，没有则明确该步需用户在登录界面手动选会话
- 给出切换 X11 会话的修复或改用支持 Wayland 抓屏的替代工具，让用户重连验证

## Stop conditions
- 连接层正常（历史有成对开始/结束记录）且抓屏报错与会话 Type=wayland 时间戳吻合，根因已定，停止继续排查网络
- 历史日志无任何"开始"记录 → 故障在连接建立之前，本方法不适用，转网络/离线/账号分支
- 工具明确走 pipewire/portal 原生支持 Wayland 且抓屏日志无报错 → 转认证、编码、带宽等其他失败层

## Verification
- 失败时刻同时出现在连接历史与抓屏错误日志中（时间戳对齐）
- 修复后用户在 X11 会话下重连成功，且工具日志不再刷 XOpenDisplay 失败

## Counterexamples
- 连接历史完全没有"开始桌面控制"记录（从未建立连接）→ 是网络/离线/账号问题，与会话显示协议无关
- 无头服务器、无任何图形会话 → 需要虚拟显示方案，切换 xsessions 不适用
- 断开发生在认证/识别码验证阶段（日志是凭据失败而非抓屏失败）→ 先修账号凭据
- 工具本身原生支持 Wayland 抓屏 → XOpenDisplay 报错可能只是兼容路径噪音，不能据此定根因
