---
title: 等值重构的验证必须先排除两个自证陷阱：镜像导入 + 用新API重算期望值
scenario: "把 world_fingerprint 拆成 world_digest().material() 的 sha256 后，需要证明\"哈希原料逐字不变\"。同一次任务里两次踩到验证自证：①直接 python3 -c 导入的是 .releases 镜像（旧代码），新旧对拍其实是旧代码自比，96 组合\"全等\"是假绿；②测试里用 world_digest().material() 重算期望值再与 world_fingerprint 比，等于拿新实现证明新实现（独立审查 P2-2 指出）。"
root_cause: ""
solution: "1) 任何对拍/验证脚本首行 sys.path.insert(0,'src')，并 assert 'src/' in module.__file__ 或打印 __file__ 作为回执证据；pytest 走 pythonpath 配置可直接信 rootdir。2) 等值锁定的期望值必须是\"拆分前实现的字面输出\"硬编码常量（golden material 串 + sha），不得调用新 API 重算——重算只能证明实现自洽，不能证明与旧行为等价。3) 同一次改动里若新增\"归因/分类\"埋点，必须检查门控链上是否存在比埋点更早的 return 路径：前台 app 切换会在 world 比对之前早退，若只在新分支加归因，最常见的一类事件永远没有分子。"
evidence: "证据链：首次对拍未加 sys.path 时输出\"96 组合全等\"但 import 的是 <workspace>/.releases/b25573b2e1c886551bdb0f9d8e3d8ac0e5f0be74/src/llm_loop/desktop/operate.py；加 sys.path.insert(0,'src') 并 assert 'src/' in __file__ 后重跑 96 组合仍全等（真实等值）。自证式测试被独立审查 P2-2 指出，改为硬编码 _GOLDEN_MATERIAL/_GOLDEN_SHA 后 test_world_fingerprint_golden_bytes_unchanged 通过（114 passed）。早退路径缺归因由代码核实：_gate_world_rebind 在 1245 行先判 fresh_window/frontmost 早退，world 比对在其后，故补 _world_gate_breaks 并加 test_u16_drift_breaks_foreground_on_early_gate_exit。"
tags: [testing, verification, self-proving-test, repo-mirror, refactor-equivalence, instrumentation]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-04T14:41:16.913682+08:00"
updated_at: "2026-11-04T14:41:16.913682+08:00"
---