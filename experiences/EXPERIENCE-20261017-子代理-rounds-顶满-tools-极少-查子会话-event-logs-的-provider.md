---
title: 子代理 rounds 顶满+tools 极少=查子会话 event_logs 的 provider 调用分布，勿猜合并计数
scenario: 子代理回执 rounds 顶满上限但 tools 极少（如 500/12），父级需判断预算计数机制与空轮根因时
root_cause: ""
solution: 先读 runner.py 确认轮次计数为子代理局部变量（每 spawn 从 0 起、预算独立），再解析 data/event_logs/<child_id>.jsonl 统计 provider.call.settled 的 outcome 分布定位空轮根因；本次根因为确定性 HTTP 400(provider_code=1214) 无熔断原样重试，烧光 500 轮预算
evidence: data/event_logs/subagent_08561ba3535e.jsonl：500 provider.call.opened / 491 transport.settled outcome=error status_code=400 provider_code=1214 / 9 success；data/event_logs/subagent_5c294b88177f.jsonl：489 error / 11 success；runner.py 行 2524、2545、2693、2660、2680、2584-2586
tags: [subagent, rounds-budget, LLMHTTPError, provider_code-1214, event-log-forensics, no-circuit-breaker]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-17T20:53:44.030087+08:00"
updated_at: "2026-10-17T20:53:44.030087+08:00"
---

现象：父级 spawn_subagent 收到 rounds=500 truncated、tools 仅 12-15，直觉误判为"父子轮次合并计算"或"模型空转"。
定位法（3 步，~5 分钟）：
1. 代码核预算归属：src/llm_loop/subagent/runner.py `_execute_subagent` 行 2524 `rounds = 0` 为子代理局部变量，effective_rounds 取子代理自身配置（行 2521-2522），父级轮次从不传入——每个子代理都是全新满额预算，绝无父子合并。
2. 子会话事件日志：data/event_logs/<child_id>.jsonl 中 provider.call.settled 事件逐条对应每轮的 LLM 调用；统计 outcome 分布即知空轮构成。
3. transport.settled 事件带 status_code/provider_code/error_type，可直接点名异常。
本次实测结论：500 轮中 491/489 轮是同一 HTTP 400（provider_code=1214）的原样重试——runner 对确定性 4xx 无熔断（行 2693 continue），失败帧不修改 wire，同一请求被拒后反复重发直至预算耗尽。EmptyResponse（行 2660）与 overflow（行 2680）已有立即返回保护，唯 4xx 缺失。
推论校验法：tokens_in ÷ 成功调用数 ≈ 单次 wire 体量（本次 ~2.5-2.8 万/次，合理）；若 ÷ 总轮数得到几百 token/轮这种不合理值，即空轮信号。
适用边界：仅验证于本仓库 subagent runner 当前版本；JSONL 事件格式以当时 schema 为准。教训：truncated ≠ 干满了预算的活，先查 settled 分布再下结论；我方上一轮"97% 模型决策空转"的表述即因未查日志而失准——实为模型根本未参与决策（调用被 400 拒绝）。