---
title: DSH 插件安装/验证五坑：DSH_HOME 双区、plugin-verify schema 不兼容 boot 崩溃、批式调用绕过 repeat-stop、tail 管道伪装僵死、job 通知为准
scenario: LFL 通过 dsh_task 派发 DSH（DeepSeek Harness）headless 任务并安装 awesome-dsh-plugin 第三方插件（repeat-stop/verify/tier-router/llm-fallbacks/capability-index/gate）后做行为实测
root_cause: "①DSH_HOME 双区：restart_system.sh:249 将服务级 DSH_HOME 重定向到项目内 data/dsh-home，手动 dsh plugin add 默认装到 ~/.dsh（用户全局区），LFL 服务 spawn 的 DSH 进程读项目内区→插件零加载；②dsh-plugin-verify@1.0.0 用 JSON Schema 语法（参数字段级 required:true + output.schema 根 required:true），cordis value schema DSL 不支持→整个 profile boot 崩溃（dump-config 不编译 schema 所以此前不可见）；③重复调用 deny 是轮次间 streak 语义，批内并行调用只触发 warn。"
solution: "①装插件前先确认服务进程 DSH_HOME（grep restart_system.sh）再 export 对应 DSH_HOME 安装；②boot 崩溃时看 [cause] 链，schema 不兼容插件从两区 package.json 的 dsh.profile.bundles 数组移除（deps 保留）；③repeat-stop 验证需串行任务（每轮一个调用），批式 tool_calls 只触发 warn 不 deny；④串行多轮任务用 shell 后台跑绕开 dsh_task 60s 工具超时；⑤job_output 长时间 0 行不等于僵死，以 interop 通知的 completed 事件为准"
evidence: "evidence://v1/a9ef5078ef895e7a18e148d67a0d8494b10edeab8f120c325b4740dc30b31ef7；evidence://v1/2a71442303da53ea40d75ce600e386fe8e5a9718d8b60d58a21388a11ff97cc3；evidence://v1/b8e4d0bd48d9830ee98da794f11669a98f0b284290c93b59c3add04acd4ca208"
tags: [DSH, DSH_HOME, 插件安装, dsh_task, repeat-stop, plugin-verify, 供应链, smoke-test]
source: {}
status: active
created_at: "2026-08-29T10:38:42.522248+08:00"
updated_at: "2026-08-29T10:38:42.522248+08:00"
---

排障链：①装插件前先 `grep -n DSH_HOME scripts/restart_system.sh` 确认服务进程实际 DSH_HOME，勿假设 ~/.dsh；②装完用 `dsh --profile headless --dump-config | grep 插件名` 验证 composed 树（此命令不编译 schema，能过不代表能 boot）；③验证工具行为要设计**串行**任务（"每次只发起一个调用，等结果再下一个"），批式 tool_calls 不触发轮间 streak；④dsh_task 有 60s 工具级上限，串行多轮任务用 execute_command run_in_background + dsh --profile headless 直跑；⑤`命令 | tail -N` 管道下 job_output 可能长时间显示 running/0 行，completion 以 interop 通知/最终 done 状态为准，勿过早判僵死；⑥插件 boot 崩溃看 [cause] 链首个 Error，schema 类错误（UNSUPPORTED_SCHEMA）→ 从 bundles 移除该插件恢复 boot（编辑 profiles/<p>/package.json 的 dsh.profile.bundles 数组，deps 保留）。