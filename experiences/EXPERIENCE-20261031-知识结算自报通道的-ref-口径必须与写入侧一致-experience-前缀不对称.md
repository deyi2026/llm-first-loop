---
title: "知识结算自报通道的 ref 口径必须与写入侧一致（experience: 前缀不对称）"
scenario: 在 llm-first-loop 用 settlement_submit 对上一轮沉淀的两张 experience 卡做自报结算时，stable ref、裸 id、文件路径三种形式全部 failed，reason 为 self_reported ref not found；而实际使用已被 refine_experience 记入 ledger，看起来像「结算通道坏了」。
root_cause: "代码里校验侧与写入侧的 ref 口径不对称：_submit_one 的 self_reported 分支用 store.get(ref) 校验存在性，而 experience 的写入侧 record_use 走的是 ref.removeprefix(\"experience:\")。于是合法的 stable ref（experience:EXPERIENCE-xxx）被交给按文件名解析的 store.get，必然找不到；而真正能命中的 key 是去掉前缀后的文件名。上游 experience 卡的 stable ref 带前缀，正是模型最可能照抄的形式，所以失败看起来像随机。"
solution: 两处：(1) 代码修复——校验侧按 kind 归一（experience 去前缀，method 原样），使校验口径与写入口径一致，并加回归测试 test_submit_tool_self_reported_experience_accepts_prefixed_stable_ref。(2) 流程侧——先确认 store 的真实 key 形态再提交：experience 的 key 是「文件名去掉 .md」，不是带前缀的 stable ref，也不是路径。本轮实测：裸文件名形式提交两张卡 → committed=2；带前缀形式在修复后 → committed=1。
evidence: "修复后实测：settlement_submit 以 ref='experience:EXPERIENCE-20260101-test-card' 提交 → counts.committed=1（evidence://v1/6f58765512d4c6b5bdd8692ed91a389e8dd529da52c57a145420b7c1b92e8a3e 为代码修复回执）；回归 tests/unit/test_settlement_tools.py 21 passed，结算相关两文件合计 53 passed 无回归。"
tags: [settlement, knowledge, bug, ref-format]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T20:25:35.728964+08:00"
updated_at: "2026-10-31T20:25:35.728964+08:00"
---