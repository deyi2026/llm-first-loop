---
title: "ci_gate 在分支上变红时，用\"父提交 worktree + 同一 ratchet 脚本\"做归因，而不是猜"
scenario: "提交一个小修复后按 RULE-AI-28 走独立审查+全量门禁，ci_gate 在 [3/5] pyright 步 BLOCK：new=2，但报错文件 provider_routes.py 根本不在本次改动里（changed_file_diagnostics=0）。需要判断这是本次提交引入的，还是分支上早已存在的债务，否则会把别人的债算到自己头上、或误以为要回滚。"
root_cause: ""
solution: |
  步骤（全程只读，各 ~2 分钟）：
  1) 在干净 worktree 里跑到提交版本：git worktree add --detach .worktrees/verify-<tag> <commit>，在其中走完整准入+ci_gate，记录 new= / changed_file_diagnostics= 两个数。
  2) 再建一个 worktree 指向父提交：git worktree add --detach .worktrees/parent-<sha> <parent>。
  3) 只跑被 BLOCK 的那一步脚本（不是整个 ci_gate，省掉准入与全量 pytest）：
     PY=<主检出>/.venv/bin/python; PYTHONPATH="$(pwd)/src" "$PY" scripts/check_static_diagnostics.py --tool pyright
     注意 PYTHONPATH 必须指向当前 worktree 的 src，否则 editable 安装会把被测代码锚回主区（ci_gate 头部注释同款理由）。
  4) 对比：父提交也 new=2 且是同样的两条 BLOCK ⇒ 预存债务，本次提交无责；父提交 new=0 ⇒ 是本次引入，必须修。
  本次实测：19758ec79 上 new=2/changed_file_diagnostics=0；父提交 fdd40e0ab 上 new=2/changed_file_diagnostics=2（同两条 provider_routes.py reportOptionalMemberAccess）⇒ 结论为分支预存债务，来自更早的 web/model-admin 提交。
evidence: "REVIEW candidate_sha256=9f0f1ca6f0e6a42315b67a343bfcdf80ac9f79ca0516246fffdecc5013c1dc4e (PASS, workdir=.worktrees/verify-rv-20261028@19758ec79)；ci_gate job-7f199ec37e274e659c18 exit=1，[1/5]R9 ruff PASS、[2/5]env-pin PASS、[3/5] R9 pyright new=2 BLOCK x2 provider_routes.py；归因 job-9899a2a007bc4870af46 在 .worktrees/parent-fdd40e0 (fdd40e0ab) 上输出 new=2 且同样两条 BLOCK。"
tags: [ci_gate, pyright, ratchet, attribution, worktree, RULE-AI-28]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T21:52:46.889574+08:00"
updated_at: "2026-10-28T21:52:46.889574+08:00"
---