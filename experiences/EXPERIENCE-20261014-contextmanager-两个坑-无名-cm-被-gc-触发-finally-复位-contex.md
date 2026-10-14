---
title: contextmanager 两个坑：无名 CM 被 GC 触发 finally 复位 contextvar；CM 内调同锁访问器死锁
scenario: 在 Python contextmanager（contextlib）封装的 contextvar/锁语义上做测试或观测性采集
root_cause: contextvars 的 set/reset 与 contextmanager 生命周期耦合：(a) reset 在 finally，CM 被 GC 即触发；(b) CM 持有的锁覆盖整个 with 体，体内同锁访问即自锁。
solution: 规则：凡 contextmanager 内 set 的 contextvar，消费方必须在 with 体内消费（CM 持引用），禁止内联 __enter__()；凡 CM 持锁跨越 yield 的，with 体内禁止调用需要同锁的访问器——facts/观测采集移到 CM 外或 CM 前。死锁症状：pytest 单测挂起无输出（无 timeout 插件时）——先怀疑同线程锁复入。
evidence: tests/unit/test_effect_fence_layer_codes.py 中的 _probe_authority docstring 记录了坑1；src/llm_loop/core/tool_execution_journal.py effect_mutation_authority 注释记录了坑2（EVO-20261014-459a8a1e 实现，commit 33a64baa5）
tags: [python, contextmanager, contextvars, deadlock, testing, observability]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-14T19:02:26.313628+08:00"
updated_at: "2026-10-14T19:02:26.313628+08:00"
---

两个独立但同源的坑：
1. 内联 contextmanager：`journal.effect_context(...).__enter__()` 不持引用，CPython 引用计数立即回收 CM → 生成器 close() → finally 块执行 → `_current_effect_binding.reset(token)` 把刚设置的 binding 复位。表现为"下一行读 contextvar 永远是 None"，且最小复现脚本可能与测试环境表现不同（取决于临时对象存活窗口）。正确写法：`with journal.effect_context(...) as ...:` 或持有 CM 变量。
2. contextmanager CM 持锁横跨 yield：`SessionStore.run_generation_authority` 持 `_run_save_tokens_guard` 直到 __exit__。在 with 体内再调用 `active_run_generation()`（同锁）→ 同线程死锁，pytest 无超时表现为挂起。CM 内做观测性 facts 采集必须在进入 CM 之前读（接受 best-effort 竞态）。