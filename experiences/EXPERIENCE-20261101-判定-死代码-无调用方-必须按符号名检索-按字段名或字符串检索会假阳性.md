---
title: "判定\"死代码/无调用方\"必须按符号名检索，按字段名或字符串检索会假阳性"
scenario: "接手\"接上死代码\"类任务时，需要先证明某实现确实无调用方。本次核对新增视图函数 compose_service_identity_with_guard_freshness 的调用链，先 grep 其产出的字段名 \"guard_code_drift\"，在 tools/builtin/service_control.py 中零命中，据此断言\"新函数是死代码、工具层没切换\"。复检按函数符号名 grep，发现第 27 行已 import、第 308 行已调用，链路完整——断言当场作废。"
root_cause: "把\"实现产出的数据键\"当成\"实现的身份标识\"来检索；包装/透传式改动中二者刻意不同名，检索口径与待证命题不匹配。"
solution: "证明\"X 无调用方\"时，检索键必须是被调用符号本身（函数/类/常量名），不能是它生成的字段名、日志串、配置键或文档措辞——字段名与符号名不同名是常态（包装函数、透传子结构）。步骤：① grep 符号名（含从 X import 的 from-import 形态）② grep 调用点 .X( 与 import 语句两路交叉 ③ 对\"透传/包装型\"改动额外核对执行路径是否切换了被调函数名，而不只是数据块里多了键。任一命中即撤回\"死代码\"结论。切勿在仅搜字段名后先行宣布结论：假阳性会直接推翻已发出的判断，且容易诱导做无谓的\"修复\"。"
evidence: "grep -rn \"guard_code_drift\" src/llm_loop/tools/builtin/service_control.py → 零命中；grep -rn \"compose_service_identity_with_guard_freshness\" src/ tests/ → src/llm_loop/tools/builtin/service_control.py:27 (import)、:308 (调用)、src/llm_loop/runtime/service_control.py:1752 (定义)，两处均在 release 产物 .releases/f47b923d4 中同样存在。"
tags: [code-nav, grep, 死代码判定, 证据口径, 假阳性]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-01T13:55:55.728557+08:00"
updated_at: "2026-11-01T13:55:55.728557+08:00"
---