---
title: review_host_admission.py 改动会撞 function_size 棘轮守卫：start/_target 增长需同步重登记基线
scenario: "在 llm-first-loop 仓库修改 src/llm_loop/tools/review_host_admission.py（给 full_test 冻结基准/首次推送 ref 等逻辑）后跑 scripts/ci_gate.sh 全量门禁，pytest tier0 预检阶段 tests/unit/test_arch_guards.py::test_function_lines_ratchet_within_baseline 红：报「棘轮增长 start: 登记 77 → 实测 81（零增长）」与「未登记 _target: 实测 122 ≥120 且不在 function_lines∪legacy」。改动文件本身 ruff/pyright 全绿（changed_file_diagnostics=0），所以静态诊断门禁不会提前暴露这个问题，只有 pytest 守卫会红。"
root_cause: ""
solution: 改 review_host_admission.py 前先看 tests/guards/function_size_baseline.json 的 function_lines 登记值：start 登记 77 行（棘轮零增长，任何增长即红）、_target 登记阈值 120 行（≥120 必须登记）。两条出路：(a) 把 start 收缩回 ≤77 行、把 _target 压到 <120 行（推荐，棘轮只降不升，重登记抬高基线属另一套 guard 策略）；(b) 跑 python scripts/regen_function_size_baseline.py 重登记（守卫自己给的提示，guard(r9) 前缀提交），但这会抬高基线、与棘轮方向相反。归因方法：用 base 提交与 HEAD 各自 AST 实测同一函数行数（base start=77/_target=107 → HEAD start=81/_target=122）并确认 tests/guards/function_size_baseline.json 不在本次 diff 内，即可判定红由本候选引入而非分支旧债。
evidence: "job-6398a1b01c7d42f79c50（exit=1，1 failed, 340 passed, 2 skipped, 14414 deselected）；evidence://v1/cf09ef4bac38aed075d08cbc1b33c79cb13235c2be54894e74203160a373024d（断言原文）；/tmp/lfl_measure_fn.py AST 实测 base 0c9281eea1d54a81e72fe3e2adf67ba0a630617e vs HEAD 353464bb7d0265b94581422df8ad0579da058450"
tags: [ci_gate, arch-guard, function-size-ratchet, review_host_admission, python]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-12T10:51:37.819707+08:00"
updated_at: "2026-11-12T10:51:37.819707+08:00"
supersedes: [EXPERIENCE-20261101-加字段前先跑架构守卫-跨-plane-导入与封顶函数行数是两条会咬人的零增长棘轮, EXPERIENCE-20261108-worktree-跑全量门禁前-补-venv-软链-改行数类代码后先-git-add-再验-arch, EXPERIENCE-20261030-r9-棘轮门双口径-未-stage-的工作树修复对守卫不可见-勿误判为重构无效]
---