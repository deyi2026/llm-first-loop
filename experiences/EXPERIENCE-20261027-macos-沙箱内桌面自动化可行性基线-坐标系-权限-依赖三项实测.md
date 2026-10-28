---
title: macOS 沙箱内桌面自动化可行性基线：坐标系/权限/依赖三项实测
scenario: 在 LFL 的 execute_command（macOS sandbox-exec，仅可写工作区/缓存）内评估或实现桌面 GUI 感知与操控前的可行性判断
root_cause: 三项硬约束互相独立：(1) screencapture -R 的入参是逻辑点、出图是物理像素，Retina 下差 2 倍，视觉坐标直接当点击坐标必偏；(2) osascript 驱动 System Events 报 -10004，可能是 TCC 未授权也可能是沙箱拦 Mach IPC，二者修复路径不同；(3) 系统 python 3.9.6 无 pyobjc，swiftc 报 permissionDenied，窗口 id/几何无现成通道
solution: 1) 坐标合同：对外统一用点，截图回执必带 scale，像素→点除以 scale，视觉坐标点击前必须 dry_run；2) 权限归因：先在非沙箱终端跑一次 osascript 判定沙箱拦截 vs TCC 缺授，再决定做独立宿主进程还是仅授权；3) 依赖分层：lsappinfo 可在沙箱内列出 app/bundleID（白名单判定够用，无需 AX），screencapture -R 可做区域截图，控件级 AX 需 pyobjc 或独立进程，未通过前不承诺
evidence: "evidence://v1/881fb1a1c6cdb3900dc021b8e880effb023e2c73329fa84740fe9c1dfdd8c000（-R 0,0,200,100 → 400x200 像素，证明点/像素 2 倍）; evidence://v1/a78fa5a3ab4c941516ed5dcf697bd8f1c65abc18cd6ad50947416dfd49b5749a（lsappinfo 可用 / swiftc permissionDenied / pip 21.2.4）; evidence://v1/468a057a7cff374a91114fc566630fd8b7416607e264107151d73bb12539b0ab（screencapture 全屏 3024x1964 成功、osascript -10004）"
tags: [macos, desktop-automation, sandbox-exec, retina-coordinate, ax-api, feasibility]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-27T10:46:15.293678+08:00"
updated_at: "2026-10-27T10:46:15.293678+08:00"
---

实测环境：macOS Retina 3024x1964（逻辑 1512x982），python3 3.9.6，sandbox-exec 生效。

关键判据：
- `screencapture -x <path>` 在沙箱内成功（8.1MB PNG），说明屏幕录制权限可用。
- `screencapture -R 0,0,200,100` 产出 400x200 像素 → -R 输入为点，输出为像素，比例 2.0。任何"视觉定位→点击"链路必须除 scale。
- `screencapture -l 0` 报 could not create image from window → 窗口级截图必须先有真实 CGWindowID。
- `osascript -e 'tell application "System Events" ...'` 报 -10004，沙箱内的 System Events 通道不可用；但无法在沙箱内区分是 TCC 未授权还是沙箱拦截。
- `lsappinfo list` 可用，能拿到 app 名与 bundleID → 应用级白名单判定不需要任何系统授权。
- `python3 -c "import Quartz"` 失败；`swiftc --version` 报 permissionDenied → 现场无法编译 Swift helper，pyobjc 也没有。

落地建议顺序：应用级感知（lsappinfo）→ 区域截图（-R，带 scale）→ 权限归因实验 → 独立宿主进程 + AX。不要把"再加一个工具函数"当成桌面操控的工作量估算。