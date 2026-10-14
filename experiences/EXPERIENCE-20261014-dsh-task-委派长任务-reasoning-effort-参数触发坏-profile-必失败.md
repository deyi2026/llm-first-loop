---
title: dsh_task 委派长任务：reasoning_effort 参数触发坏 profile 必失败；前台 60s 超时但进程存活，从 session.v4.jsonl.zstd 取报告
scenario: 需要委派长时独立审核/多步 git 核验任务（试合并+定向测试），本会话 dsh_task 前台 60s 包装超时、且带 reasoning_effort 参数必失败
root_cause: ""
solution: "1) dsh_task 不传 reasoning_effort；2) 长任务接受 60s 工具超时报错，之后用 pgrep -fl \"dsh --profile headless\" 盯进程、ls /tmp 等产物目录，进程退出后从 data/dsh-home/sessions/<工作目录名>/session-*/session.v4.jsonl.zstd（zstdcat）提取 type=assistant/message 中 content type=text 的最后一块作为最终报告"
evidence: "evidence://v1/e75419d9174fe92a0e7a78239123b4f4e71030f525e4bf04258ca7b73f3cea6c; evidence://v1/2940133238b5dfcd8955257dc66c1c47c6a54e023dc8188d9ee95501860ce191"
tags: [dsh_task, reasoning_effort, 60s-timeout, session-log, 委派审核]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T17:34:08.873292+08:00"
updated_at: "2026-10-14T17:34:08.873292+08:00"
---

2026-10-14 实测（会话内二分验证）：dsh_task 带 reasoning_effort 参数（如 high）时 0.4s 即失败，stderr 指向 data/dsh-home/logs/startup-*.log，报错 agent-default-model 的 $.provider missing required value（configurationPath=data/dsh-home/profiles/headless/cordis.yml），实际 cordis.patch.yml 里 provider 完好——带该参数会走坏的 repo 本地 profile 组合路径。去掉 reasoning_effort（用 profile 默认 reasoningEffort: max）即正常。另：dsh_task 前台调用超过 60s 会被本会话工具包装层报"执行超时"，但底层 `dsh --profile headless` 进程存活继续跑；用 pgrep -f "dsh --profile headless" 确认，产物/日志在 data/dsh-home/sessions/<cwd路径转换的目录>/session-*/session.v4.jsonl.zstd，用 zstdcat 解包后提取 type=assistant/message 且 content[].type=='text' 的最后一块即最终报告（reasoning 块不是）。dsh_session_read 工具读不到这类 headless 会话（默认指向 ~/.dsh/sessions 的旧目录）。