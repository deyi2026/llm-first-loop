---
title: SSE 请求驱动改后台任务：后台线程+事件总线订阅+跨入口互斥（断连不中断）
scenario: 把请求驱动的流式 run（SSE 生成器）改造为后台任务（断连不中断），并安全处理并行协作下的双改冲突
root_cause: SSE 请求驱动生成器：run_stream 在请求线程 yield，连接断开 GeneratorExit 中断 run——请求驱动 vs 后台任务的架构差异。
solution: ① 后台线程消费生成器：BackgroundRunner.start 注册 RunHandle + 起 daemon 线程，copy_context 传播 contextvar，迭代 run_stream（生成器本体不改）→ delta 入事件总线；② 事件总线广播：每订阅者独立 queue（subscribe/unsubscribe），emit 快照副本广播，断连 unsubscribe 只停订阅；③ SSE 端点改提交+订阅：_stream_background 消费队列分片 yield SSE，finally unsubscribe；④ 跨入口互斥：engine.run_stream 入口检查 runner.is_running（非流式/飞书/CLI 经 engine.run 同步包装自动覆盖），后台线程自身 is_worker() 放行（否则自调用死锁）；⑤ 回退开关 RUNNER_BACKGROUND=0；⑥ 双改冲突化解：发现并行 agent 增强 runner/engine（SessionBusyError/is_worker）后不覆盖，验证合并态+全量测试通过后收编提交，分组 commit 注明协作。
evidence: 2026-08-16 实施完成：提交 4c58789（后台 run 改造）+ d22e72b；设计 docs/local/DESIGN-20260816-background-run.md v0.3；8 个 runner 单测 + 全量单测通过；协调消息 010/011 与 DSH 协作（并行 agent 增强 runner/engine 已合并验证）。
tags: [后台run, SSE, 事件总线, 线程, 跨入口互斥, 双改冲突, is_worker]
source: {}
status: active
created_at: "2026-08-16T23:04:16.784876+08:00"
updated_at: "2026-08-16T23:04:16.784876+08:00"
---