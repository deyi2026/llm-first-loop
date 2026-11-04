---
title: eval 自检的套件数断言按机器本地目录计数校准，与 git 跟踪口径漂移会同时造成 checkout 自检 FAIL 与 release 快照 FAIL
scenario: 2026-11-04 自我检查：eval/rules/selfcheck.py 断言「evals/ 域内套件数 = 48」，但断言口径是 os.listdir(evals) 减 4 个排除项，即机器本地目录数，不是 git 跟踪套件数。本机 checkout 实际 49（46 跟踪 + 3 本地未跟踪目录 harness_evolution_v0/execution_efficiency_fcr/embedding_stage2），故 checkout 94 项 FAIL 1 项；同一断言在 .releases/28ca887e 快照里算出 46（快照只有跟踪内容）故 release 也 FAIL，且另外 4 条 FAIL 是快照缺 gitignore 产物（eval/results、eval/logs）造成的口径差，不能算作真实缺陷。断言值 48 本身对应 plan 提交时（6eabd43e6，跟踪 45）之后的某个本地状态，与两侧都不对齐。
root_cause: ""
solution: "诊断顺序：① 先分别取 git 跟踪口径（git ls-tree/ls-files 排除 4 项）与工作区口径（listdir 排除 4 项），差集即本地未跟踪目录；② 断言值与两侧都不匹配时，判定为断言校准口径过时（按本地目录数校准），而不是\"套件丢失\"或\"套件新增\"；③ 区分 checkout 与 release 快照两类 FAIL——快照额外缺 gitignore 产物属预期；④ 修复方向是把断言改成 git 跟踪口径（或显式声明的 manifest 口径）并写清数值来源，改门禁断言属 RULE-AI-28 审查范围，改前不得宣称自检已通过。"
evidence: "checkout: python3 eval/rules/selfcheck.py → exit 1, 94 项 FAIL 1 项「evals/ 域内套件数 = 48 … 实际 49」；git ls-tree HEAD evals 排除 .venv-eval/heldout/rule_redline_v1/results = 46；6eabd43e6 时 = 45；差集 3 个 = harness_evolution_v0(仅 gitignore bge_cache.json/自身被 .gitignore:131)、execution_efficiency_fcr(仅 __pycache__)、embedding_stage2(仅 gitignore 的 bge_cache.json)。release 快照 .releases/28ca887e… 跑同一脚本 → 64 项 FAIL 5 项（套件数实际 46 + eval/results/…/results.json 缺失 + eval/logs/baseline_v0_full.log 缺失 + 基线 sha256 全可复算 + 归因器可执行），后 4 条均为 gitignore 产物不在快照所致。"
tags: [eval, selfcheck, 门禁断言, 口径, git跟踪, 自我检查]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-04T08:54:50.934125+08:00"
updated_at: "2026-11-04T08:54:50.934125+08:00"
---