---
title: 沙盒内无法给 Chrome 开 --force-renderer-accessibility（unix socket 被拒）；网页层语义改走 CDP
scenario: 要让 macOS AX 读到 Chrome 网页层（AXWebArea），直觉路径是起一个带 --force-renderer-accessibility 的独立 Chrome 实例；本会话在 sandbox-exec 内两种起法都失败，需要拿到根因而不是再试第三种。
root_cause: ""
solution: "根因是沙盒禁创建 unix domain socket：直接启动 Chrome 报 \"Failed to create a socket directory\" → \"Failed to create a ProcessSingleton for your profile directory\" → abort（同期普通文件写入正常）；open -na 在沙盒内 exit 0 但根本不派生子进程（无新 pid、profile 目录全空），即 LaunchServices 交接被静默丢弃。因此沙盒内任何方式都起不了带 flag 的实例，只能由人在自己终端起。替代通道：对 CDP 9229 实例的全部 page target 发 Accessibility.enable，再 getFullAXTree，可拿到完整网页层 AX 树（本次 8463 节点，含 button/heading/link）；但 macOS AX 侧复测 Chrome 仍只有 AXWindow/AXGroup/AXButton(close·min·fullscreen)，无 AXWebArea，开完 CDP AX 也不变 → Chrome 网页层走 CDP，AX 只服务原生 app 与窗口 chrome 级动作。当前性验证：重跑 `pgrep -x \"Google Chrome\"` 看是否出现带 flag 的新 pid；再 `desktop_perceive(action=snapshot, window_id=<该 Chrome 窗口 id>)` 看树里是否出现 AXWebArea；或直接查 Chrome 启动日志是否仍报 \"Failed to create a socket directory\"。"
evidence: "本次实测回执：Chrome 启动日志 \"Failed to create a socket directory.\" / \"Failed to create a ProcessSingleton ... Aborting now\"；open -na 后 pgrep 无新 Chrome pid（仅原有 61931、96579）、profile 目录为空；CDP /json/list 得 12 个 page target，Accessibility.enable 全部 ok，getFullAXTree nodes=8463；desktop_perceive snapshot 三个 Chrome 窗口（115037/pid 96579、121487/pid 61931、118258）均无 AXWebArea。"
tags: [desktop, chrome, ax, cdp, sandbox, root-cause]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T16:02:37.399061+08:00"
updated_at: "2026-10-31T16:02:37.399061+08:00"
supersedes: [EXPERIENCE-20261031-chrome-ax-激活受阻-沙盒内第二个-chrome-实例因-processsingleton]
---