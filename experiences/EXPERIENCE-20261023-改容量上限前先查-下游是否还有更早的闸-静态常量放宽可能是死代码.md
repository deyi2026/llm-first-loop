---
title: "改容量上限前先查\"下游是否还有更早的闸\"：静态常量放宽可能是死代码"
scenario: "要放宽一个门禁的静态上限（如 review_admission 的 _REVIEWER_STATIC_MATERIAL_CAP_BYTES），让真实产物能通过。直觉做法是\"把常量改大\"。实测发现只改常量完全无效：有效闸 = min(静态, 动态)，动态闸仍夹住；且下游 child 是空工具子代理，超预算时拒绝而非截断，于是变成\"预检放行、child 仍拒\"——比原来更糟（误报 reviewer_unavailable 并烧掉重试预算）。"
root_cause: ""
solution: "改容量类门禁前，先把\"有效闸\"链路完整读出来并逐环实测：(1) 静态常量；(2) 动态闸 = min(静态, min(物理窗口, registry×headroom))；(3) 下游消费者的实际比较单位与超限行为（拒绝 vs 截断 vs 投影）。三环必须同口径同单位，否则任一环不变则整体行为不变。特别注意单位混用：静态按字节、动态按字符时，放宽静态后仍会被动态按更小的字符预算拒掉。本次把静态上限、动态闸 token 口径、预检与 child 的共用函数三处同时改为同口径（字符 vs 字符、同一个 _wire_chars_per_token），并把预检单位从 bytes 改为 chars（child 侧比较的是 sum(dict_wire_chars(m))），才真正生效。"
evidence: "src/llm_loop/tools/review_host_admission.py 有效闸 = min(_REVIEWER_STATIC_MATERIAL_CAP_BYTES, int(model_budget * _REVIEWER_WIRE_HEADROOM))；src/llm_loop/subagent/runner.py _bounded_child_wire 超预算走\"拒绝静默截断\"路径；evals/results/review_cap_change_20261023/gate_outcome.txt 记录改前 REFUSED / 改后 ACCEPTED + ×1.1~×2.0 全部 REFUSED；tests/unit/test_review_host_admission.py 160 passed"
tags: [gate, capacity, review-admission, unit-consistency, RULE-AI-35, dead-code-change]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-23T19:12:01.842896+08:00"
updated_at: "2026-10-23T19:12:01.842896+08:00"
---