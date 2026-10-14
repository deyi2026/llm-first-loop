---
title: 引入新打断边界后既有边界语义测试的三类适配判别法（归属更新/关闸保机制/锚点加固）
scenario: 在既有打断/检查点体系（Phase4 gap 收割 + Phase5 流式打断）之上引入新的更早消费边界（Phase6 同步窗口轮询 sync_window_poll）时，编码了旧边界语义或贴边时序的既有测试会失败/翻面，且失败形态与真回归难以区分。
root_cause: ""
solution: 按失败形态分三类处置，判别依据是失败样本的 consumed_via 归属值与注入时点相对新旧边界的距离：(a) 注入时点落在旧边界机制的目标窗口内、断言旧边界语义 → 显式关闸（新增配置门=False）保留机制测试原意，旧边界仍服务晚到插话与关闸回退；(b) 断言的是「构造↔归属机械一致」的归属测试 → 归属值更新为新边界真相（不关闸），final_gate 归属由关闸回退测试另行覆盖；(c) 注入余量贴边（<60ms）的时序脆弱测试 → 加固注入锚点至确定性命中点（如段间检查点），目标值随锚点重定并注明理由。禁止把 (a)/(b)/(c) 误判为引擎真回归而回滚。当前性验证：见 body 末行可执行命令。
evidence: "evidence://v1/e868890188c75743e1e5370ee8a9eeeb3fd03aa0a0f322314149d2f807989c2a（m3 归属更新后全绿）；evidence://v1/372f227cecb8ffc5dafd92b4f86bd70521a4cef3a6f036945ae8dc137ef456a7（test_b 加固 3/3）；evidence://v1/d0f84f24088d6f62358e2e1ab158e1b03717438b29f719ae1fe2c004c05bea81（全量 8800/0）"
tags: [interrupt-checkpoint, test-adaptation, timing-fragility, boundary-semantics, phase6]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T18:40:25.835386+08:00"
updated_at: "2026-10-13T18:40:25.835386+08:00"
---

Phase6（同步 chat 通道异步化）实施期证据：

1. Phase4 m3 llm_stream 桶测试（窗口内注入→断言 final_gate）在全量回归失败——M1 在同位置引入了更早的合法边界（窗口轮询），归属真相变了。适配=更新断言为 sync_window_poll（机械归属一致性保留），关闸适配则用于「机制测试原意是旧边界」的场景（phase3 CBF、phase4 序列头收割）。

2. test_b（工具执行期注入→断言 gap 收割 skip）间歇失败：M1 每轮线程开销收窄了其 40ms 注入余量；加固=锚点前移到段间检查点确定性命中 + 目标值随锚点重定并注明理由。

3. 判别法：新边界引入后既有断言失败，先读失败样本的 consumed_via/t_effect/断言目标三方——归属值变化=适配断言（关闸或更新）；时序余量收窄=加固锚点；真缺陷=修代码（本例 R6 终检缺失、peek 裸调两处均由 red/回归发现）。

当前性验证：grep -n "sync_window_poll" tests/phase4/test_m3_bucket_metrics.py 应命中归属断言；.venv/bin/python -m pytest tests/phase4/test_m1_gap_checkpoint.py -q 应 3/3 passed（0.5s 锚点在位）；.venv/bin/python -m pytest tests/ -q 应 0 failed。