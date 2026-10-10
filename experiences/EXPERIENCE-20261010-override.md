---
title: 配置文件默认值≠有效运行配置：断言链路状态前必须核调用点与服务级 override
scenario: "断言某机制\"当前仍在运行/已关闭\"时，只读了 .env 默认值与 architecture_status 状态视图（含 top_injected 累计统计），据此得出\"memory 扁平 top-K 注入仍是现行瓶颈\"\"语义检索全关\"等结论，被外部核对部分推翻。"
root_cause: "把\"配置文件里的值\"当成\"运行中的行为\"，把\"统计视图的旧值\"当成\"链路活跃\"——两处都是用静态快照推断动态链路，缺少调用点核验。"
solution: "凡断言\"某链路当前在/不在运行\"：(1) grep 该链路关键函数在生产代码（src/）中的调用点，定义存在≠被调用；(2) 配置以服务级 override 为准（runtime.toml per-service 段、dry-run/eval 工件里的 effective 值），.env 只是全局默认；(3) 累计型统计（inject_count）冻结不代表故障，可能是调用点已移除；先查调用点再定性。"
evidence: "search_files 回执：mark_injected 在 src 仅 store.py:515 定义无调用方；_runtime_memory_top_k 在 src 内 3 处均为定义/转发、无消费方；factory.py:2287 注释确认 memory_top_k 自适应回调悬空。evals/retrieval_ab/fr1-activation-dryrun-20261006.json 与 docs/PLAN-20261006-fr1-semantic-method-activation-authz.md 记录 Learning 服务级 override SEMANTIC_METHOD_ENABLED 0→1。"
tags: [effective-config, config-override, runtime-verification, static-vs-dynamic]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-10T00:18:17.459717+08:00"
updated_at: "2026-10-10T00:18:17.459717+08:00"
---

2026-10-10 OpenViking 对照分析中，依据 .env（MEMORY_TOP_K=5 / SEMANTIC_METHOD_ENABLED=0）与 architecture_status（top_injected 统计、memory_state）断言了三条链路状态：(1) memory 自动 top-K 注入仍在运行——被 src grep 推翻；(2) 语义检索全关——被服务级 override 工件部分推翻；(3) top_injected 停滞疑似统计故障——实际是调用点已不存在，统计为遗留视图。核实方法：grep 调用点（mark_injected / _runtime_memory_top_k）+ 服务级 override（runtime_toml_service:learning）+ PLAN/dry-run 工件。