---
method_id: xshm-fails-every-client-check-xserver-ipc-namespace-owner-unit-dc3daf550dad
name: xshm-fails-every-client-check-xserver-ipc-namespace-owner-unit
description: X11 下远程控制/录屏工具（向日葵、ffmpeg x11grab 等一切走 XShm 的客户端）报 SHM 段级错误且桌面本身渲染正常时，先做判别复现：换一个无关全新客户端采集，若同样失败而 Xorg 日志显示 MIT-SHM 已初始化、/dev/shm 健康，则故障不在任何应用，而在 X server 与客户端的共享基底——IPC 命名空间隔离（System V 共享内存按 ns 隔离）。用 /proc/<pid>/ns/ipc inode 对比实证，再按 PPid/cgroup 找到拥有 Xorg 的 systemd unit（先定归属再读属性），查其 PrivateIPC 等沙箱指令；用包管理历史对照重启时间解释『重启前好、重启后坏』。修复是 unit override 三行配置，不是重装系统。
aliases: 向日葵连上但画面全黑, 远程工具抓屏拿不到图像数据, 升级重启后远程控制黑屏, Xorg 和客户端不共享内存, 显示管理器沙箱导致黑屏, error 128 XShm 采集失败
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1352:b51daed79d82b288dd9c
evidence_refs: learning:learn:77c54343fc72
created_at: 2026-10-29T16:35:33.936222+08:00
updated_at: 2026-10-29T16:35:33.936222+08:00
---
## Trigger
X11 会话下基于共享内存的屏幕采集失败：远程控制/录屏客户端日志报 SHM 段级错误（BadShmSeg、error 128、cannot get image data→display lost），本地截图证明桌面在正常渲染，现象常出现在系统升级+重启之后，用户问是否要重装系统

## Discriminator
用无关全新客户端（如 ffmpeg x11grab）复现同一 SHM 段错误 + Xorg 日志显示 MIT-SHM 扩展已初始化 + /dev/shm 健康 + 采集端服务自身无沙箱 ⇒ 同时排除应用与其服务配置，唯一剩下的能隔离 SysV 共享内存的机制就是 IPC 命名空间

## Short path
- 二分渲染 vs 采集：本地截图亮度正常 ⇒ 桌面在渲染，问题在采集链路，直接排除重装系统
- 读采集端自身日志拿具体错误：进程 cmdline 常带 --log-file=，厂商日志常在 /var/log/<vendor>/，先沿这两条线索再考虑全盘 find；确认为 SHM 段级错误而非连接/认证错误
- 判别复现：用无关全新客户端走同一 XShm 路径采集，同样失败 ⇒ 假设从『该工具的问题』切换为『X server 与所有客户端之间的共享被隔离』
- 实证隔离：对比 /proc/<Xorg>/ns/ipc 与客户端 ns/ipc 的 inode；同时用 Xorg 日志扩展已加载、/dev/shm 正常排除其余解释
- 先定归属再读属性：用 PPid + cgroup 确认哪个 unit 启动了 Xorg，再读该 unit 的 PrivateIPC/PrivateTmp/ProtectSystem 等指令——不要按『哪个 unit 看起来更严格』去猜（本集曾先追错到 seatd）
- 用 apt/dpkg 历史时间戳对照重启时间，解释激活边界；修复=对该 unit 做 override 关闭隔离指令并重启，最后用远程工具+全新客户端双重验证

## Stop conditions
- 已实测 ns inode 隔离并定位到拥有 X server 的 unit 沙箱指令（如 PrivateIPC=yes），给出 override 修复即可停
- 全新客户端能正常采集 ⇒ 隔离假设证伪，回到该工具自身（缓存/配置/版本）排查
- Xorg 与客户端本在同一 IPC 命名空间 ⇒ 转查 X 权限/auth、显卡驱动或工具配置

## Verification
- 修复并重启该 unit 后，重测 /proc/<Xorg>/ns/ipc 与客户端 inode 一致，且全新客户端与远程工具采集均恢复画面
- 时间线自洽：unit 指令/升级生效时间 晚于 上次远程正常工作时间、早于故障首发时间

## Counterexamples
- 只有目标工具报错、ffmpeg 等全新客户端采集正常 ⇒ 是该工具自身问题，不要动显示管理器
- Wayland 会话（不走 XShm 路径）或 Xorg 日志无 MIT-SHM ⇒ 命名空间假设不适用，按会话协议不匹配/扩展缺失处理
- 错误是 XOpenDisplay failed、连接即断等连接/认证层错误 ⇒ 属会话类型或链路问题，不是共享内存隔离
- X server 由用户会话内进程直接启动、无 systemd 沙箱 ⇒ 没有 unit 指令可查，转查 auth 与权限
