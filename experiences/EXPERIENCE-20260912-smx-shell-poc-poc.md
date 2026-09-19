---
title: smx shell 域 PoC 结论：可回验性真实存在，PoC 规模下效率收益未量出
scenario: 对 LLM shell 操作加结构化回执层（rc_chain/fs diff/落盘回执）是否提升任务表现，做 6 任务×A/B 对照（冻结件协议，judge 预写死边界）。
root_cause: ""
solution: 按冻结件 PoC 验证法执行：selftest 18/18（含 13 负例拒绝）、12 run 全 judge=true。
evidence: tools/smx/lab/.runs 全量回执（12 run judge=true）；selftest 18/18 exit=0（.runs/selftest.log）；EVO-20260912-10818cb5 审计四态。
tags: [smx, poc, ab-test, frozen-protocol, shell]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-12T09:39:19.733676+08:00"
updated_at: "2026-09-12T09:39:19.733676+08:00"
---

结论（PoC 规模，n=12）：
1. 可回验性升级真实：rc_chain 捕获裸 shell 静默吞掉的管道中段失败（ls /no/such | head → rc=0 但 chain=[1]）；fs 净 diff 直接给出；回执落盘可重放。
2. 效率收益未量出：B 组工具调用数/耗时与 A 组基本持平（唯一明显 T2 shell 7→3）；引用 0-3 次/任务，有任务完全不用。
3. 已知盲区如实标注：窗口内创建又删的瞬时变化不可见；exit N 时 chain 不可用；均写入回执不静默降级。
决策：接入与否等 2026-10-12 R2 复查 + dogfood 定性样本后裁决；当前 CLI-only。