---
title: Deepin 25 ddm PrivateIPC=yes 致 MIT-SHM 失效：向日葵黑屏 + dde-lock 黑窗的根因定位与修复
scenario: Deepin 25 + ddm 显示管理器，向日葵远程黑屏；桌面实际正常渲染（截屏非黑），dde-lock 全屏窗口渲染成黑窗
root_cause: ""
solution: ddm.service override PrivateIPC=no + /etc/ddm.conf 配 Autologin（X11 会话），重启 ddm 生效
evidence: "execute_command 回执：PrivateIPC_BEFORE=[yes]/AFTER=[no]（evidence 16:57 提权执行）；最终验证 X11+XShm rc=0+灰度14-212+无dde.lock全屏窗（verify_final.sh 17:01）"
tags: [deepin, ddm, PrivateIPC, MIT-SHM, sunlogin, black-screen, x11, wayland]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T16:58:24.106811+08:00"
updated_at: "2026-10-29T16:58:24.106811+08:00"
---

症状：Deepin 25 远程（向日葵）黑屏但桌面实际在渲染（登录会话正常）。
诊断链：1) ssh 从 dde-session-daemon 的 /proc/PID/environ 抓真实 DISPLAY/XAUTHORITY（重启后会变，别用缓存值）；2) ffmpeg -f x11grab 截屏取 4x4 灰度判断"桌面在不在画"（区分渲染层 vs 采集层故障）；3) ffmpeg stderr 的 error_code:128 major_code:130 = XShm BadAccess → MIT-SHM 不可用；4) xwininfo -root -children 找全屏遮挡窗（dde-lock 3120x2080 黑窗）。
根因：ddm.service（SDDM fork，Deepin 25 新 DM）默认 PrivateIPC=yes，X 会话进独立 IPC namespace，MIT-SHM 跨 namespace 失效 → dde-lock 渲染失败叠黑窗、向日葵采屏黑帧。
修复（均需 root）：systemd override 写 /etc/systemd/system/ddm.service.d/override.conf [Service] PrivateIPC=no；ddm restart 后若停 greeter（Wayland 界面向日葵采不到、远程无法输密码死锁）→ 写 /etc/ddm.conf [Autologin] User=<u> Session=deepin（X11，不带 .desktop 后缀）再 restart ddm。
陷阱：① Wayland/treeland 会话下向日葵完全不采集，务必锁 X11（xsessions/deepin.desktop）；② apt 升级 dde-kwin/移除 deepin-kwin-x11 分包发生在诊断中途会污染时间线，先查 /var/log/dpkg.log；③ kill dde-lock 只是临时救急；④ 不要留 pkill dde-lock 的 watchdog 常驻，会破坏正常锁屏，根因修复后应移除。