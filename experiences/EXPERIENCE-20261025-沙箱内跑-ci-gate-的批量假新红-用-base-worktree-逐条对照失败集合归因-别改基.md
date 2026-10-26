---
title: 沙箱内跑 ci_gate 的批量假新红：用 base worktree 逐条对照失败集合归因，别改基线也别改代码
scenario: 在 agent 沙箱（macOS sandbox-exec）内跑仓库全量门禁/全量 pytest，出现大批「未登记新红」且既有登记红全部 STALE，需要判断是代码回归还是环境伪红
root_cause: ""
solution: 用 base commit 的 detached worktree 跑同一批失败测试，比对 FAILED 集合是否逐条相同；并把 TMPDIR/HOME 指到工作区内做交叉印证。集合相同即归因环境，不改代码、不改 known-reds 登记，改为如实上报并交 owner 在非沙箱环境跑同一命令取权威结论。
evidence: "ci_gate 回执 29 failed（登记命中 0，全是 NEW-RED）；evidence://v1/19355d37999457d250f1f12cf0411b738873fee53b7ccd8bf79976537c1439b5 行 2495-2629 含完整 29 条与 3 条 STALE；直接单跑 test_execute_command_scrubs_env.py → 9 passed；带门禁 HOME + 默认 TMPDIR → 失败堆栈含 \"python3: error: couldn't create cache file '/var/folders/.../xcrun_db-...' (errno=Operation not permitted)\"；TMPDIR 改到工作区内 → 22 failed/150 passed；base 31e8662b4 detached worktree 同条件 → 22 failed/150 passed；broken-TMPDIR 场景 base 与候选 FAILED 列表 diff 为空（27/27 IDENTICAL_SETS，文件 .tmp-ci/{base,cand}_broken_tmpdir.txt）"
tags: [ci_gate, sandbox, 假红, base对照, known_reds, TMPDIR, 全量测试归因]
source:
  project: llm-first-loop-mirror
  branch: fix/evo-e0bff8ee-p2-int-20261025
  task: EVO-20261025-e0bff8ee + P2 修复的全量门禁
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-25T11:11:52.661287+08:00"
updated_at: "2026-10-25T11:11:52.661287+08:00"
---

## 症状
在 agent 的 execute_command（macOS sandbox-exec 包装）里跑仓库全量门禁 `bash scripts/ci_gate.sh`，得到 `29 failed / 175 tests`，且 known-reds 对账显示「登记命中: 0」（3 条既有登记红一条都没红）、29 条全被判为 NEW-RED。失败横跨 installer 脚本、mailbox setgid 校验、进程 kill、fs escape、env 清洗等互不相关的模块 —— 这种「跨模块、彼此无关、且已知红反而变绿」的分布本身就是环境信号，不是代码回归信号。

## 根因（实测）
1. 外层沙箱拒绝写 TMPDIR（`/var/folders/.../T/`）。macOS 的 `python3` 是 xcrun shim，写缓存失败会在子进程 stderr 打出 `python3: error: couldn't create cache file ... (errno=Operation not permitted)`。凡是断言「stderr 为空」「子进程环境干净」的测试立即变红（本次 `test_execute_command_scrubs_env` 4 条）。
2. 沙箱同时拦截：越界写（symlink escape 类断言）、setgid 目录属性（`test_task_budget_operator_mailbox` 4 条）、子进程 kill/进程树断言（`test_assurance_p1_process_reviewer` 8 条）、root 目录写收据（`test_restart_preflight_source` 3 条）。
3. 门禁把 `HOME` 指向 `<repo>/data/.ci-test-home`，使 xcrun 缓存从零创建，放大了 (1)。

## 判别方法（可复现，约 1 分钟/次）
1. 用**同一 worktree 的 base commit** 建 detached worktree：`git worktree add --detach .worktrees/base-cmp <base_sha>`，`mkdir -p .tmp-ci/tmp data/.ci-test-home`。
2. 在 base 与 candidate 两边跑**同一批失败测试文件**，`grep -E '^FAILED' | sort` 落盘，`diff` 两份列表。
3. 若两份 FAILED 集合逐条相同（本次 27/27 IDENTICAL_SETS）→ 归因环境，候选无新增红。
4. 交叉印证：把 `TMPDIR=$PWD/.tmp-ci/tmp HOME=$PWD/data/.ci-test-home` 指到工作区内再跑，红数应从 29 降到 22（7 条纯 TMPDIR 噪声），且剩余 22 条与 base 一致。

## 边界与结论
- 该现象**只在沙箱包装的 shell 里出现**；owner 在普通终端跑同一命令通常全绿。所以 agent 在沙箱内**不能**产出可信的「全量通过」结论，也不应为了让门禁变绿去改 `eval/rules/known_reds_current.json`（那是「直接豁免」，门禁脚本自己写着禁止）。
- 正确收口：① 用 base 对照把 29 条定性为环境；② 如实报「全量未通过，原因环境，无候选新增红」；③ 把 `bash scripts/ci_gate.sh` 交给 owner 在非沙箱环境跑，才有权威结论。
- 反例（别踩）：看到 red 就去改代码或改基线。本次 29 条里与改动模块重合的只有 `test_execute_command_scrubs_env`（P2-3 改过 execute_command.py），但它在 base 上同样红、且单跑 9/9 通过 —— 不做 base 对照就会误判成自己引入的回归。