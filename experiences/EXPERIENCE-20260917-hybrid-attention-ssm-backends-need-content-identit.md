---
title: "Hybrid attention+SSM backends need content-identity reuse gates, not timing-only checks"
scenario: "Qualifying prefix-cache reuse on llama.cpp backends, especially hybrid attention+SSM architectures (falcon-h1, jamba, qwen3-next class): timing-only reuse gates can pass while generation content silently changes, and cache_n semantics drift from token-prefix semantics."
root_cause: ""
solution: "Layered: (1) determinism audit as an abort-on-fail pre-gate inside every gate runner (greedy repeats bit-identical on cold + cache-replay paths); (2) generation-content identity checks in the canary (exact replay and A-after-divergent-B must match the cold reference bit-identically); (3) account reuse only from server-reported values, use locally computed token LCP solely as an upper-bound guard and candidate selector; (4) bind evidence to build_info + operator-declared device label and hash raw outputs."
evidence: "StateBraid commits 506db30/88a0ffd/9d857fc/a57c3db；pinned build 465e49b9c 上 determinism audit PASS + 12/12 canary PASS（Metal），CPU 档同 PASS；553/1059 边界跨 build×device 复现；raw 证据 sha256: 652bbd4f…(audit) 6a473428…(metal canary) 031e2d41…(cpu canary)"
tags: [llama.cpp, prefix-cache, hybrid-ssm, qualification, determinism]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-17T00:58:19.775878+08:00"
updated_at: "2026-09-17T00:58:19.775878+08:00"
---

场景：对 llama.cpp 系后端做前缀缓存复用资格化时，纯 timing 检查（cache_n ≤ 真实 LCP）全部通过，但生成内容可能已因 SSM 状态损坏而悄悄改变；hybrid 架构上 cache_n 语义本身也随快照粒度漂移（实测 1065 前缀分叉后只复用 553，真 LCP 1059，两个 build × Metal/CPU 全一致）。方案：(1) 确定性审计作为强制 pre-gate（greedy 重复 N 次 bit-identical，冷/缓存重放双路径）；(2) 内容恒等检查（exact 重放与 A-after-B 生成必须 bit-identical 于冷参考）；(3) 记账只用 server 回报值，本地 LCP 只做上界守卫与候选选择；(4) 证据必须钉 build_info + 设备标签，raw 输出留哈希。