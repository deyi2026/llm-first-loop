---
title: 已发布 web 的页面级实测：鉴权隔离 fixture 化 + LFRT 准入回退 + 后台 run + SSE 页面 domcontentloaded
scenario: 对生产 web（鉴权开启、密码 operator 私有、无 WEB_API_KEY）需要页面级验证新发布特性（如 EVO-20260920 工作区切换/新建会话解耦），或 fixture 实测遇到 ResourceAdmissionError/流式指示不出现/run 随浏览器关闭中止等问题
root_cause: ""
solution: 用同代码隔离 fixture（env 覆盖法）+ 8901 本地模型 + playwright_exec(domcontentloaded) 分段实测，以 UI testid/按钮文案为锚点、以服务端事件日志与分区文件为落盘 oracle
evidence: "data/e2e/gen57-pagetest/Z2/Z3/Z4 截图；fixture 事件日志（run.end 答案 1+1=2；1ee24105 跨切换持续 partial_checkpoint 落盘默认分区）；lfrt runtime-observation 实测输出 {\"managed\":true,\"managed_port\":8901,\"state\":\"unknown\",\"reason\":\"runtime_identity_conflict\"}"
tags: [页面实测, fixture, playwright_exec, LFRT准入, RUNNER_BACKGROUND, web鉴权, gen57]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-20T19:51:14.978854+08:00"
updated_at: "2026-09-20T19:51:14.978854+08:00"
---

对已发布 web（如 gen57）做"页面实测"时，按以下顺序排障可避免五轮盲试：1) 认证面：prod WEB_AUTH_REQUIRE=1 时若无 WEB_API_KEY 且密码 operator 私有，浏览器 cookie 通道不可得（session 为进程内存态），应直接转"同代码隔离 fixture"方案：cwd=repo 根（identity 要求），env 显式覆盖 DATA_DIR/WEB_PORT=8913/WEB_AUTH_REQUIRE=0/LLM_BASE_URL=127.0.0.1:8901，环境变量优先于 .env（load_env_file 不覆盖已设键）。2) LFL 运行时父环境会注入 LFL_LOCAL_RUNTIME_ADMISSION_AUTHORITY=lfrt/LFL_LFRT_CLI——loopback provider 会走 LFRT 准入，lfrt runtime-observation 报 state=unknown(runtime_identity_conflict) 即 ResourceAdmissionError(required_fact_unknown)；fixture env 必须显式回退 legacy+disabled。3) RUNNER_BACKGROUND 默认 True（浏览器关闭只停订阅、run 继续落盘）；显式设 0 会让 run 随 SSE 客户端断开而死。4) playwright_exec：goto 必须 wait_until="domcontentloaded"（SPA 常驻 SSE，networkidle 30s 必超时）；外层 60s 硬截断，长流程拆多次调用，每次动作前先 js 诊断态。5) 本地 MLX server 冷启动首 token 可达 17-47s，先 curl 预热；空视图首发的 streaming 态会被会话回填订阅者重置（conversation.ts L156），先完成一次短问答锚定会话再发长文，流式指示稳定。UI 断言锚点：[data-testid=ws-tree-head]/new-session/composer-input、按钮文案"发送"↔"■ 停止生成"、.v2-ws-tree-node.current、失败文案"工作区切换失败"。