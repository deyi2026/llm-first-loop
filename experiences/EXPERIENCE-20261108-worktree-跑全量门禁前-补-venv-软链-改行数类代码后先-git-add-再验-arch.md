---
title: worktree 跑全量门禁前：补 .venv 软链；改行数类代码后先 git add 再验 arch guard
scenario: "在 git worktree 里跑 canonical 全量门禁（scripts/ci_gate.sh），出现两类\"看似代码红、实为口径/环境\"的失败：(1) test_env_preflight 断言缺\"实测版本\"；(2) test_arch_guards 的行数棘轮报\"实测 377 > 登记 376\"，但 AST 直接量是 376。"
root_cause: "conftest 的 env preflight 用 `_PROJECT_ROOT/.venv/bin/python` 测版本，worktree 没有 .venv 时该路径不存在，诊断报文缺\"实测版本 x.y\"→断言失败。arch guard 的源码口径是\"未 staged 的文件回退到 HEAD 版本\"，所以工作区已改但未 add 时，行数仍按 HEAD 计算。"
solution: |
  跑 worktree 全量前先做两件环境对齐：1) `ln -sfn <主树>/.venv <worktree>/.venv`（.venv 在 gitignore，不污染产物），再单跑 tests/unit/test_env_preflight.py 应为全绿。2) 修完影响函数行数的代码后，先 `git add <文件>` 再跑 tests/unit/test_arch_guards.py——否则测试读 HEAD 旧版本，你会看到"改了却没生效"的假红。判定口径：`git status --porcelain` 里该文件从 ` M` 变 `M ` 才算被测到。
  当前性验证：`ls <worktree>/.venv/bin/python && PYTHONPATH=$PWD/src <venv>/bin/python -m pytest tests/unit/test_env_preflight.py tests/unit/test_arch_guards.py -q` 应全绿。
evidence: 同一个 worktree：缺 .venv 时 tests/unit/test_env_preflight.py 1 failed（实测版本正则不匹配）；建 .venv → 主树 .venv 软链后 12 passed。改 config.load_settings 后 arch guard 报 377（读 HEAD），git add 后立即 52 passed，AST 实测 end_lineno-lineno+1=376。
tags: [worktree, ci-gate, arch-guard, environment-alignment]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-08T21:29:14.923541+08:00"
updated_at: "2026-11-08T21:29:14.923541+08:00"
supersedes: [EXPERIENCE-20260919-worktree-ambient-env-enforce-identity-venv-workspa]
---