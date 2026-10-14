---
title: web 发布模型：publish=release 快照+产物 hash 绑定，restart 两阶段等会话结束才切代
scenario: webui 改动后验证与上线：构建了新 dist 但运行中的 8903 端口仍是旧 UI；playwright goto 到 LFL UI 页面 networkidle 超时。
root_cause: ""
solution: 1) 用 lsof 找到 `python -m llm_loop.runtime.launch web` 的真实端口与 pid，curl 其 HTML 里 assets/index-*.js 的 hash 对比 .releases/<gen>/webui/dist 即可判定当前代；2) publish（要求 tracked 树干净，untracked 不阻塞）创建新代快照 .releases/<commit-hash>/，restart 受理后等请求方会话结束+目标空闲自动执行；3) SSE 页面不要 goto networkidle，改用组件级测试或重启后 js() 断言。
evidence: service_control publish 回执 generation 250 + .releases/9755869622762c5a600feb8c62ad4c9d9ad2f49f/webui/dist/assets/index-CIHhDjI5.js 存在；运行中 8903(pid 81233) 仍 serve gen249 的 index-BAaxFy_E.js（curl 比对）；playwright_exec goto 8903/ui/v2 networkidle 超时回执
tags: [service_control, web-deploy, playwright, webui]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T13:40:01.458011+08:00"
updated_at: "2026-10-13T13:40:01.458011+08:00"
---

本仓库（llm-first-loop-mirror）web 服务不走工作区热加载：publish 时把当前 git HEAD 完整快照进 .releases/<commit-hash>/（含 webui/dist 产物，产物 hash 与 desired manifest 绑定），restart 是两阶段——受理后要等请求方会话结束且目标空闲才真正执行。推论：改完 webui 直接 npm run build 不影响运行中服务；验证新 UI 必须等 restart 完成后看端口切到新 release 目录。publish 前置校验 git status --porcelain --untracked-files=no 必须为空，untracked 文件不阻塞。另：playwright_exec 的 helper 是同步七件套（goto/click/fill/wait/js/axtree_text/screenshot），禁止 import playwright；goto 固定等 networkidle，对开 SSE 长连接的 LFL UI 页面会 30s 超时——此类页面改用组件测试或重启后用 js() 断言。