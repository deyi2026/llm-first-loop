---
title: 沙盒内起不了第二个 Chrome 实例（ProcessSingleton socket 目录不可创建），Chrome AX 激活需沙盒外或改服务启动参数
scenario: 想在 LFL 沙盒进程里用 `--force-renderer-accessibility` + 独立 `--user-data-dir` 起一个可控 Chrome 实例，以便让 AX 树可达网页内容（AXWebArea）。
root_cause: Chrome 的进程单例锁依赖在 profile 目录创建 unix socket；沙盒策略只放行工作区与缓存目录的写，其余 socket 创建被拒，Chrome 以避免 profile 损坏为由主动 abort。
solution: "沙盒内起独立 Chrome 实例会在创建 profile 锁时 abort：`Failed to create a socket directory` → `Failed to create a ProcessSingleton for your profile directory` → 进程自行退出（即使 user-data-dir 指向可写的 /tmp）。`open -na \"Google Chrome\" --args ...` 也无效：既没起新实例（user-data-dir 未被创建），也不会在既有 Chrome 里开探针页。可行路径只有两条：(a) 在沙盒外起带 flag 的实例；(b) 给服务自带的 chatgpt-web Chrome（profile data/runtime/chatgpt-web-chrome-profile，端口 9229）加 `--force-renderer-accessibility` 后重启服务——这是部署/环境决策。现状复核：服务 Chrome 主窗口 AX 树 33 节点但 AXWebArea=0、AXStaticText=0，确认网页层不可达。"
evidence: "evidence://v1/37c3d625a1977ef12c1a8f5dd2064a81148d97bdad193f24087462082b6deb28（Chrome 启动日志：Failed to create a socket directory / ProcessSingleton abort）、evidence://v1/a7c5f3（现存服务 Chrome AXWebArea=0 复核）"
tags: [chrome, ax, sandbox, accessibility, deployment]
source: {}
status: archived
record_kind: experience
verification_state: verified
created_at: "2026-10-31T15:20:21.121843+08:00"
updated_at: "2026-10-31T15:20:38.060237+08:00"
---