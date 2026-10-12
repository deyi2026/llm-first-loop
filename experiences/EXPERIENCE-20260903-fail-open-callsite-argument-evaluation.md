---
title: fail-open-callsite-argument-evaluation
scenario: "observer 类 fail-open 函数（内部全吞异常）的调用点，其实参在调用方求值——测试桩 arguments 为 str（违反生产 dict 契约）时 `dict(tc.arguments or {})` 在进入函数前就抛 ValueError，穿透 fail-open 语义破坏调用方控制流，全量门新增红"
root_cause: ""
solution: "fail-open 观测调用的实参必须防御式构造：`args=tc.arguments if isinstance(tc.arguments, dict) else {}`——非法形态降级为安全默认（空 dict）而非让求值异常上抛；教训通用化：凡\"内部全吞\"的函数，其**实参表达式**仍是调用方的裸奔区，契约校验要在实参侧完成"
evidence: ""
tags: [fail-open, 观测插桩, 参数求值, 防御式调用, 异常边界]
source: {}
status: active
qualification: 2026-09-18 batch2/3 per-file review: retained（methodology self-evident：步骤可机械复现或含实测细节；evidence 内嵌正文）
created_at: "2026-09-03T16:37:38.234493+08:00"
updated_at: "2026-09-03T16:37:38.234493+08:00"
---