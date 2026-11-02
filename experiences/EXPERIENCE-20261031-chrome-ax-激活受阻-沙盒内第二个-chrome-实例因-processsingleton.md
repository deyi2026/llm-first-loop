---
title: Chrome AX 激活受阻：沙盒内第二个 Chrome 实例因 ProcessSingleton socket 目录不可创建而 abort（更正证据版）
scenario: 想在 LFL 沙盒进程里用 `--force-renderer-accessibility` + 独立 `--user-data-dir` 起一个可控 Chrome 实例，让 AX 树可达网页内容（AXWebArea）。
root_cause: ""
solution: "沙盒内起独立 Chrome 实例会在创建 profile 锁时 abort：`Failed to create a socket directory` → `Failed to create a ProcessSingleton for your profile directory` → 进程自行退出（即使 user-data-dir 指向可写的 /tmp）。`open -na \"Google Chrome\" --args ...` 同样无效：既没起新实例（user-data-dir 未被创建），也不会在既有 Chrome 里开探针页。可行路径只有两条：(a) 在沙盒外起带 flag 的实例；(b) 给服务自带的 chatgpt-web Chrome（profile data/runtime/chatgpt-web-chrome-profile，端口 9229）加 `--force-renderer-accessibility` 后重启服务——属部署/环境决策。现状复核：服务 Chrome 主窗口 AX 树 33 节点但 AXWebArea=0、AXStaticText=0，确认网页层不可达。"
evidence: "Chrome 启动失败日志：evidence://v1/a14dbc02ec15f68abac7a973b289e01e660dace9b3095276636876558d64a493；首次直启未成实例：evidence://v1/37c3d625a1977ef12c1a8f5dd2064a81148d97bdad193f24087462082b6deb28；服务 Chrome AXWebArea=0 与探针页无残留：evidence://v1/6f30b2a3ef1bc084d267f40a3638a9a9a54fd8e6ec80b07bebe33e49a4a168ae"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T15:20:48.199630+08:00"
updated_at: "2026-10-31T15:20:48.199630+08:00"
---