---
title: 跨进程 liveness 权威源不存在时，自备探针会把「重启后仍活」误判为死亡；谓词必须注入式
scenario: "为 lane 生命周期收尾设计 liveness 判据时，设计稿先写「探针优先级：session_registry.is_running（权威）→ lane_events 最近事件（弱）→ unknown 不收口」。实测核查发现：本仓不存在跨进程会话存活权威源——BackgroundRunner.is_running 只查进程内 registry（重启后必然 false），web/queue_recovery.py:176 的 _alive 同构，data/audit/ 下无 session/run/lease 账本。若按设计稿自备探针，跨进程场景下会把「另一个进程里仍活着的会话」判成死亡并回收其工作树。"
root_cause: 把「进程内可见性」误当成「全局权威性」——跨进程与重启场景下，进程内 registry 的否定结果不构成死亡证据。
solution: 把 liveness 谓词改为注入式：宿主经 host.lane_liveness_probe(session_id) -> alive|dead|unknown 注入，实现不注入即 liveness_unavailable 且零动作（fail-closed）。关键细节：探针返回 False（跨进程不可见）不等于 dead，实现归为 unknown 不收口；弱证据（lane_events 最近事件时间）只用于否决（当作活着），不能用于判死。这与本仓既有先例 queue_recovery._alive「能力缺失时保守跳过」一致。
evidence: "子代理只读调研（runner.py:405 进程内集合、queue_recovery.py:176 同构、data/audit 无 session/run/lease 账本）；实现落点 src/llm_loop/introspection/lane.py reap_candidates（探针缺失/抛错/返回 False 一律 unknown 或 unavailable）；实测 R2-d PASS 见 docs/design/receipts/P2-r35-20261114.json；用例 tests/unit/test_lane_reap.py::test_probe_false_is_not_death 与 ::test_probe_exception_is_not_death。"
tags: [liveness, fail-closed, lane, cross-process, rule-ai-30]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-14T15:02:52.371866+08:00"
updated_at: "2026-11-14T15:02:52.371866+08:00"
---