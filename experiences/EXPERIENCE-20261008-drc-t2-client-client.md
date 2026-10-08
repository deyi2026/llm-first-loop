---
title: DRC T2 迁移第二 client：逐字复用首迁 client 契约结构 + 镜像故障注入测试
scenario: DRC（DESIGN-20261007-durable-run-contract）存量持久化面按 tier 迁移：第二个 T2 client（service_control_state `_atomic_json`，2026-10-08 commit 97d1eff43）。此前首迁 client 为 ScheduleStore 主状态（scheduler.py `_commit_state`）。
root_cause: ""
solution: 逐面复用首迁 client 的两阶段写路径契约而非重新发明：replace 前 tmp O_EXCL+file fsync+os.replace（有界重试+清理 tmp），replace 后仅重试目录 fsync；typed outcome 分型 + 持单写者锁的逐字 readback。验收=镜像 test_schedule_durability.py 手法的故障注入测试 + 既有回归 + arch guards；registry status 升级与设计文档实施记录同 commit 闭合。
evidence: "commit 97d1eff43（guard(r9): service_control_state partial → conform）；tests/unit/test_service_control_durability.py 7 passed；service_control -k 回归 250 passed；test_arch_guards.py 21 passed；ruff 对比 HEAD 零新增"
tags: [durable-run-contract, t2-migration, service-control, fsync, commit-uncertain]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-08T08:43:38.471377+08:00"
updated_at: "2026-10-08T08:43:38.471377+08:00"
---

迁移手法：新 client 完整复刻首迁 client（ScheduleStore）的分相结构——模块级 `_write_temp_exclusive/_fsync_directory/_payload_visible_state` helper（测试经 monkeypatch 模块属性注入故障）、typed outcome 异常对（definitely_not_committed / commit_outcome_uncertain+expected_sha256+visible_state）、有界重试常量。验收三件套：故障注入新测试（normal 无 tmp 残留、pre-replace 分型+旧态保留、post-replace uncertain+no-rewrite 计数、预算内恢复、readback unreadable、集成两态）+ 既有回归面 -k 选择器跑绿 + arch guards（durability_registry 校验）。lint 用 HEAD 版本对比确认零新增。关键语义钉子：post-replace 阶段对同一 semantic mutation 只重试目录 fsync；uncertain 后 CAS 场景用旧 expected_generation 盲重放必须被冲突错误机械拒绝（写成显式测试）。
当前性验证：grep -n "_STATE_PERSIST_ATTEMPTS" src/llm_loop/runtime/service_control.py 应命中定义行；python3 -m pytest tests/unit/test_service_control_durability.py -q 应得 7 passed。