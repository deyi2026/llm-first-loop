---
title: spawn 子代理不跨模型回合存活：必须本回合轮询收取，或改用同步通道
scenario: LLF 会话内需要独立子代理执行审查/复核类任务：spawn_subagent 是异步的，若父模型在派发后结束回合，运行时会以 cancelled_on_model_final 取消该子代理；服务重启也会杀掉运行中子代理。
root_cause: ""
solution: 不要「派完就走」。同步模式在本会话实测有效：spawn 后在本回合内 subagent_result(wait_seconds≤30) 轮询；轮询间隙用 wait 工具（1-120s 零模型调用）拉长间隔；接近预算上限用 agent_message 发「立即收尾」指令；subagent_result 回执 child_state=completed 才算拿到交付物。dsh_task 为同步备选但本环境启动失败（exit 1）。跨回合需求才用 wake 排程，且 wake 依赖的 owner pid 在重启后可能失效、需到点验证。
evidence: "event_stream 2026-10-12T21:43:19 async.obligation cancelled_on_model_final ids=subagent_93dfe7362cb1；subagent_result(subagent_93dfe7362cb1) cancelled/2轮/2工具；subagent_result(subagent_79ba1e6c20a8) completed/9轮/37工具/报告完整；subagent_lease 两者 state=settled"
tags: [subagent, async-lifecycle, spawn, cancelled_on_model_final, wait, agent_message, 审查流程]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-12T22:11:28.486465+08:00"
updated_at: "2026-10-12T22:11:28.486465+08:00"
---

现象：两次独立审查子代理均未跑完。(1) subagent_da559ddca119 于 21:36:40 服务重启时被杀；(2) 重派后我在 spawn 回执显示 running 时结束回合，事件流 21:43:19 记录 async.obligation cancelled_on_model_final——异步子代理随父模型回合终结被取消，仅完成 2 轮 2 次调用。
有效做法（本回合实测跑通）：spawn_subagent(inherit=false, requires.tools=只读白名单) → 循环 subagent_result(wait_seconds=30) 轮询 → 间隙用 wait(90-120s) 纯墙钟阻塞省模型调用 → 超预算时 agent_message 发收尾指令 → subagent_result 拿到 completed 与最终报告（subagent_79ba1e6c20a8：9 轮/37 工具/510K in/53K out，REVISE 报告完整交付）。
备选通道：dsh_task 同步阻塞，但本环境启动即退（0.7s exit 1，日志 data/dsh-home/logs/），不可依赖，先试 spawn+轮询。
适用边界：审查/调研类可同步等待的任务；若必须跨回合存活的编排，用排程 wake（注意 owner pid 绑定在重启后可能失效，需到点验证）。