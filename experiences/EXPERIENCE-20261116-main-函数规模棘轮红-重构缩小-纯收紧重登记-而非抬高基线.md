---
title: main 函数规模棘轮红：重构缩小 + 纯收紧重登记，而非抬高基线
scenario: main 因某提交把函数写到超过基线（tests/guards/function_size_baseline.json）却没重登记，导致 test_function_lines_ratchet_within_baseline 在 main 上即红，任何 PR 都无法在绿门下合并；此时有人会顺手跑 scripts/regen_function_size_baseline.py 把基线抬高。
root_cause: ""
solution: |
  不要用「抬高基线」来修红：独立 push 闸审查会把基线抬高读成「放宽架构守卫」并判 REVISE/P1（即使脚本允许、即使有 EVO 泛化授权），因为审查者看不到具体批准链。正确姿势是「重构缩小到基线内」：把该函数里新增的成组分支原样抽成同文件私有 helper（返回对象/判定顺序/边界条件逐字保留），使函数回落到 ≤ 原登记值，再跑 regen 得到「抬高 0 条、收紧 N 条」的纯收紧重登记——这类 diff 审查者不会拦（本次 4 条收紧 0 抬高，闸一次 PASS）。落地要求：抽取后必须跑语义相关测试（错误分类/降级/failover）+ arch guards 全绿，并在提交信息里写明「revert 后基线回到哪一值、守卫为何复红」，避免审查者追问回退后果。
  
  当前性验证：先 `grep -n "def test_function_lines_ratchet_within_baseline" -A 20 tests/unit/test_arch_guards.py` 确认棘轮判据（登记 vs 实测、零增长）仍在且未改名；再 `python scripts/regen_function_size_baseline.py --check` 应输出「两段结构 + head_commit」校验通过（幂等）；若 push 闸实现改为「基线 diff 一律人工批准」，本条姿势需重评。
evidence: main 9e4defc0e 的 CI run 43830112457 = failure（classify_llm_error 登记 127 → 实测 137）；按脚本重登记（抬高 127→137）被 push 闸判 REVISE(P1 放宽架构守卫，subagent_f4dd3b324039)；改为抽取 _glm_code_semantics（137→114）后重登记为「抬高 0、收紧 4」→ 闸 PASS（subagent_0bf994e96d70），CI 门禁 pass 8m33s。
tags: [函数规模棘轮, arch_guards, review_admission, 重构, CI红]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-16T17:33:06.173284+08:00"
updated_at: "2026-11-16T17:33:06.173284+08:00"
---