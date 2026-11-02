---
title: 加字段前先跑架构守卫：跨 plane 导入与封顶函数行数是两条会咬人的零增长棘轮
scenario: 给既有系统加字段/接死代码时，改动跨模块多层（runtime + introspection + tool）。以为只是加几行，结果被架构守卫判红：runtime 反向 import introspection 新增跨 plane 边；两个已封顶函数各 +1~+4 行。
root_cause: "仓库有两条机械守卫：Kernel v1 import edges 冻结跨 plane 边；function-lines 对封顶函数零增长。它们只在 tests/unit/test_arch_guards.py 里跑，且以\"登记基线\"比对，改动前不看就跑全量会晚发现；靠\"重新登记基线\"消红还会顺带抹掉别人的既有债。"
solution: "1) 动手前先跑 `pytest tests/unit/test_arch_guards.py` 看清冻结项与封顶项，把\"我要加的东西落在哪一层\"先算出来：原语放 kernel 内部根（core/ 等，runtime->core 不计跨 plane 边），业务判定留上层。2) 新增字段优先挂到\"调用方整体透传\"的既有子结构上（如每服务项的 live），而不是新建顶层键——调用方只换被调函数名，行数不变。3) 需要包一层时用新函数包装（如 compose_X_with_Y），新函数有自己的行数预算，不占用封顶函数。4) 收尾必须做 A/B：`git worktree add` 取 HEAD~1 跑同一测试，逐条比对报错清单，证明\"零新增\"；不要用重登记基线来消红。5) 顺手核 ruff：删掉旧 import 可能留下未平移的调用点（本次 F821 就是漏改了另一处 call site）。"
evidence: "首提交 35c932627 被判红：test_kernel_import_edges_match_frozen_baseline（新增 runtime->introspection）+ function_lines（compose_service_identity_view 151→155、tools/builtin/service_control.py::execute 140→141）。改为 core/guard_code.py 原语 + compose_service_identity_with_guard_freshness 包装后复绿；本改动在 function_lines 报错清单上零新增，与 HEAD~1 worktree 逐条一致（5 条既有债）。最终 tests/unit 全量：38 failed / 9832 passed，与基线 39 failed / 9799 passed 的失败差集仅 1 条基线侧偶发（env_preflight）通过，无新增失败。提交 2984a9eaa。"
tags: [架构守卫, 棘轮, 导入平面, 改动前先跑守卫, A/B验证]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-01T13:33:05.913009+08:00"
updated_at: "2026-11-01T13:33:05.913009+08:00"
---