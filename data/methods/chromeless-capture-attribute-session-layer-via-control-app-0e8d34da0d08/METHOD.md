---
method_id: chromeless-capture-attribute-session-layer-via-control-app-0e8d34da0d08
name: chromeless-capture-attribute-session-layer-via-control-app
description: GUI 应用经注册表/进程表确认已在运行后，为核验用户可见界面而截屏，若画面只含壁纸且无任何系统 chrome（无菜单栏/Dock/桌面图标），这是会话/显示层事实而非应用层事实。此时不再对目标应用做 activate 重试或重复截屏，而是用一次系统对照应用（如计算器）归因：对照应用 open 后 windows=0 且画面不变 ⇒ 本会话无 GUI 合成输出，结论闭合。随后只按用户底层目的补一项权威证据（服务连接/日志），报告环境约束与后台就绪状态。典型场景：SSH/无物理显示会话中验证远程控制类 GUI 工具。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:c9d5b6ae-ee14-49e3-bde2-335797e7e621:0:01c9d5e11b3a9353bb2d
evidence_refs: learning:learn:20bcf4894e1d
created_at: 2026-10-20T10:45:21.982786+08:00
updated_at: 2026-10-20T10:45:21.982786+08:00
---
## Trigger
桌面系统上，目标 GUI 应用已被进程表/生命周期注册表确认在运行（System Events 亦报 visible=true），为核验用户是否真的能看到界面而执行 screencapture

## Discriminator
截屏缺失的不只是目标窗口，而是全部系统 UI chrome（无菜单栏、无 Dock、无桌面图标）——该事实在当时即可把候选从『应用没画窗口/窗口被隐藏/应用故障』缩为『本会话没有向被截屏表面合成任何 GUI』；再以一次系统对照应用（如 Calculator）open 后 windows=0 且画面不变完成系统级归因。

## Short path
- 先用生命周期注册表（launchctl list/LaunchDaemons）+一次进程表确认目标是否已在运行；若已在运行且用户目标只是『让它跑起来』，直接报告完成，不进入 UI 核验
- 确需核验 UI：activate 目标应用一次+screencapture 一次，观察画面是否连系统 chrome（菜单栏/Dock）都没有
- 零 chrome → open 一个系统对照应用并读其窗口数；对照应用 windows=0 且画面不变 ⇒ 会话/显示层结论成立，与目标应用无关
- 停止对目标应用的 activate 重试与对同一壁纸的重复截屏；AppleScript/System Events 查询用 alarm/超时包裹防挂起
- 仅按用户底层目的补一项权威证据（服务端 ESTABLISHED 连接、helper 日志），然后报告环境约束、后台就绪状态与可选后续路径

## Stop conditions
- 对照应用同样无窗口且截屏画面不变：归因已闭合，对目标应用的再次激活/截屏均为零信息
- 用户所需事实（在运行/可从外部连入）已由进程表与服务连接状态权威验证，停止发现

## Verification
- 结论必须同时解释两条既有观察：System Events 报 visible=true 与截屏零 UI；只解释其一则归因未闭合
- 内容相同的第二次截屏不构成新证据，归因只能由对照应用测试推进

## Counterexamples
- 截屏含菜单栏/Dock、只缺目标应用窗口 → 属应用层问题，应 activate/重启目标应用，本方法不适用
- 屏幕锁定或显示器休眠时画面同样近乎无 chrome → 先查 CGSSessionScreenIsLocked/唤醒策略排除锁屏，再下会话层结论
- screencapture 因权限被拒或返回陈旧缓存帧 → 属截屏工具自身失败类，先验证工具健康再解读画面内容
