---
method_id: x11-blackscreen-window-stack-topmost-not-process-absence-b67becd168e3
name: x11-blackscreen-window-stack-topmost-not-process-absence
description: 远程控制工具已连上 Linux X11 被控端但画面全黑时，黑屏是『栈顶渲染层被什么盖住』的问题，不是『哪些桌面进程缺席』的问题。拿到 DISPLAY/XAUTHORITY 后直接查 root 窗口树这一地面真值：栈顶若有全屏覆盖窗，用其属主进程 + logind LockedHint 区分真锁屏与登录后卡死残留；残留则 kill 属主并复查窗口树确认消失。过滤后的 ps 查不到某进程名不等于缺席（本集 kwin 曾被过滤漏判），且桌面组件名随版本漂移（dde-desktop→dde-shell），进程枚举式假设不可靠。
aliases: 向日葵连上但是黑屏, 远程桌面连上了画面全黑, 锁屏没退出来挡住屏幕, dde-lock 卡死杀掉, Deepin 远程只看到黑的, 查 X11 窗口树谁盖在最上面
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1226:6263a663c08fbc9d9155
evidence_refs: learning:learn:7a7465bcaf93
created_at: 2026-10-29T15:52:00.610921+08:00
updated_at: 2026-10-29T15:52:00.610921+08:00
---
## Trigger
远程桌面/屏幕共享工具（向日葵/ToDesk/TeamViewer 类）对 Linux 被控端连接成功但显示纯黑屏；SSH 可达、本地图形会话（X11）在跑。

## Discriminator
session env 已给出 DISPLAY/XAUTHORITY/XDG_SESSION_TYPE=x11，且 Xorg/会话进程健康、xrandr 显示显示器 connected 且 Monitor On——此时『用户实际看到什么』可由一次 xwininfo -root -tree 直接回答；黑屏应归因于栈顶全屏覆盖窗或无输出，而非基于过滤 ps 输出的『组件缺席』推断。

## Short path
- 钉死目标主机并以 SSH 身份探针（os-release/whoami）直达
- 一次批量只读探针：loginctl 会话 + ps + session env → 拿 DISPLAY/XAUTHORITY，确认显示基础设施健康（Xorg 在跑、xrandr Monitor On）
- 直接查 root 窗口树：识别栈顶全屏覆盖窗（几何=整屏 +0+0）与其属主进程，同时确认桌面应用窗口是否都在
- loginctl LockedHint 裁决：no 且锁屏组件进程/全屏窗仍在 ⇒ 登录后卡死残留；yes ⇒ 真锁屏
- 残留 ⇒ kill 该属主进程，复查窗口树确认覆盖窗消失、远程控制服务进程存活
- 交还用户重连验证，停止

## Stop conditions
- 覆盖窗已从窗口树消失且远程控制服务进程在跑
- 窗口树显示桌面完整、无异常覆盖窗（转查 DPMS/抓屏通道分支）
- LockedHint=yes（真锁屏）：停止 kill，交还用户走正规解锁

## Verification
- kill 后复查窗口树：目标全屏窗不再存在
- LockedHint 与锁屏进程状态的组合可自洽解释（未锁+进程残留=卡死，而非远程工具传错画面）
- 用户侧重连后画面可见且可控

## Counterexamples
- 会话真处于锁定（LockedHint=yes）：kill 锁屏组件等于绕过认证，应交还用户输入密码或走正规解锁通道
- xrandr 无 connected 显示器或 Monitor Off/DPMS 休眠：黑屏在输出/电源层，窗口树无覆盖窗可查
- Wayland 会话：无全局窗口树查询，本方法不适用（应走会话类型与抓屏日志对齐）
- 合成器/窗口管理器已死：窗口树查询本身失败或为空，属显示栈故障而非覆盖窗
- 栈顶是用户合法开启的全屏应用（视频/演示/游戏）：全屏≠异常，需结合窗口名与属主语义判断
