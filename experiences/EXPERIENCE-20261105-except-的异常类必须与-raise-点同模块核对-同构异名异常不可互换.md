---
title: except 的异常类必须与 raise 点同模块核对，同构异名异常不可互换
scenario: "给一个自建存储层（MergeQueueStore）加异常处理时，凭\"另一个模块（lane.LaneStore）有同名概念异常\"就 import 并 except 了 LaneVersionConflictError，而本模块实际抛出的是自己定义的 MergeQueueVersionConflictError。"
root_cause: ""
solution: "捕获异常前必须先确认该异常类的定义模块：`grep \"^class .*Error\" <模块>` 或查 import 来源，确认 `raise` 点抛出的确实是被 except 的那个类。两个模块各有一套同构异常（Corruption/VersionConflict/Constraint）时，绝不能按名字相似假设可互换。验证方式：构造并发/冲突输入跑一次，确认走的是 except 分支（回执 reason_code 出现），否则该 except 是死代码。"
evidence: "第三轮审查在 `tools_merge_queue.py` 指出：代码 `except LaneVersionConflictError`（来自 lane.py）包住 `MergeQueueStore` 的 CAS 调用，但该 store 抛的是 `MergeQueueVersionConflictError`（merge_queue.py:89 自有类）。修复前该 except 从未命中，并发冲突仍冒泡。修复：import 与两处 except 改指正确类（commit c72be2c48），150 passed。审查报告路径 data/review_admission/subagent_198241182d95-full_test.md。"
tags: [异常处理, 死代码, 多模块同构异常, 审查回执]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-05T12:13:21.896721+08:00"
updated_at: "2026-11-05T12:13:21.896721+08:00"
---