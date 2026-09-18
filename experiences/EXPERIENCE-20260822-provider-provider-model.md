---
title: 改 provider 预算前必须先确认当前会话实际使用的 provider/model
scenario: 诊断缓存命中问题时，改了 providers.json 里 deepseek 的 history_budget_chars（400K→1M）后，凭 runtime_params.history_budget=1000000 就草率判断 EM 对齐已生效，但忽略了 model 字段——当前会话实际跑的是 minimax/MiniMax-M3（minimax 仍 400K），min 链压制复现，压缩风暴未消除。这正是 honesty_rate=0.62 的典型失实场景。
root_cause: "根因：诚实声明铁律——声明的内容必须有工具回执支撑，且回执解读必须看完整字段。我上一轮看到 runtime_params.history_budget=1000000（全局装配值）就结论\"生效\"，但 provider 级 min 链下，minimax 仍是 400K；runtime_params 显示的是装配值，request.meta 的 budget 才是实际 min 链结果。两者在多 provider 环境下可能严重不一致。"
solution: 1. 改 provider 预算前，必须先查当前会话实际使用的 model（architecture_status.context_usage.runtime_params 或 request.meta.model 字段），确认 model 所属 provider 后再改对应段；不要只看全局值；2. 验证生效必须看 request.meta 的 budget 字段（权威真相源），且 budget 字段必须同时核对 model 字段——同一 budget 值在 minimax（400K）和 deepseek（1M）意义完全不同；3. 若当前模型不在你修改的 provider 范围，要么一起改，要么主动切模型。
evidence: "实测 request.meta 3 条：model=minimax/MiniMax-M3, budget=400000（2026-08-22 12:00-12:05 UTC）。action_trace 第 1 条：model_aware_budget \"minimax/MiniMax-M3: 1000000→400000\"。providers.json 修改后只有 deepseek.history_budget_chars=1000000，minimax 仍是 400000。session ad2e572c 重启后实际跑 minimax，不是配置里写的 deepseek/deepseek-v4-flash。"
tags: [provider-budget, min-chain, honesty-declaration, cache-hit-debug, preflight-check]
source: {}
status: active
created_at: "2026-08-22T20:06:26.270342+08:00"
updated_at: "2026-08-22T20:06:26.270342+08:00"
---