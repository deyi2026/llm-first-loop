---
title: 本地控制面 E2E：networkidle 永不满足时改 execute_command+playwright(domcontentloaded)，并先辨析 V1/V2 双前端实际服务入口
scenario: 本地运行面（长驻心跳 SPA）E2E 验证：playwright_exec helper goto 固定 wait_until=networkidle，控制面页面有 SSE/轮询常驻连接，30s 必超时且工具层 60s 硬限下重试脚本整包超时；同时本项目 web 有双前端：V1 static/index.html（routes.py 明示保留不删但不再服务，404）与 V2 /ui/v2/（React 构建产物，默认入口），验收口径若按 V1 文案写会误导实测入口。
root_cause: ""
solution: 改用 execute_command + 项目 venv 的 playwright（wait_until=domcontentloaded，timeout 自控、无 60s 工具层限制）；实测前先 git show --stat 定位功能提交改的是哪套前端、curl /static/index.html 探活，再对实际服务入口（V2）按 data-testid（如 im-global-bucket-*、im-global-structural-zero-*）做 DOM 断言；截图与 DOM evaluate 并取，窗口口径等视口外内容以 DOM 提取为准。
evidence: "evidence://v1/e0299265335e26b6f7a8aed169129b40d8a8f3743eea71b5e6b1823be523963a"
tags: [e2e, playwright, networkidle, webui-v2, verification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T15:06:32.240919+08:00"
updated_at: "2026-10-14T15:06:32.240919+08:00"
---

验证步骤：1) lsof -a -p <pid> 直接取运行端口；2) 先 curl API 核数据面，再区分前端入口（routes.py 根路径重定向注释是权威线索，legacy static 常为 404-by-design）；3) 浏览器渲染实测优先查 V2 生产入口的 data-testid（比 UI 文案稳定），DOM evaluate 提取结构化断言 + 截图双证据；4) task_update evidence_refs 只收 evidence:// 引用（所有工具回执自动落 evidence://v1/...，文件路径会被拒）。