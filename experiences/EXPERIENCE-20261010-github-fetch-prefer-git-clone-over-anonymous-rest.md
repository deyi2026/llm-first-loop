---
title: github-fetch-prefer-git-clone-over-anonymous-rest-api
scenario: 需要从 GitHub 获取仓库内容（文件、README、代码搜索）时的取数通道选择：匿名 REST api.github.com vs git clone。
root_cause: ""
solution: "内容类需求默认 git clone --filter=blob:none --single-branch（按需 sparse-checkout），不做匿名 REST API 重试；REST 仅用于单点元数据且失败即换路。执行前把扫描范围先窄化到子目录/文件名模式。"
evidence: "本会话事件日志（seq 453 前后）：api.github.com remaining=0 后切换 git clone --filter=blob:none 成功；codearts 会话分析报告独立复核同一事实。"
tags: [github, rate-limit, fetching, execute_command]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-10T21:16:22.279119+08:00"
updated_at: "2026-10-10T21:16:22.279119+08:00"
---

2026-10-10 会话 40eeca85 实测：连续使用匿名 api.github.com（60 req/hr/IP，且同 IP 可能被共享）后 remaining=0，REST 查询全部 403，浪费多轮。改用 git clone --filter=blob:none --single-branch 后一次成功取到所需数据。教训：对"拉取仓库内容"类需求，默认 git 协议；REST API 仅用于元数据（stars/release 等单点查询），且失败时立即换路而非重试。附带纪律：在大型仓库上跑全量 find/grep 前先限定子目录或文件名模式（本会话一次 45 万行仓库 find 超 60s 超时）。