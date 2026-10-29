---
title: 共享 mirror 仓库的全量测试、归因与提交纪律（job_id 免疫 / 陈旧锁 / 文件交换归因 / 显式路径 add）
scenario: 在多会话并发写入的共享 git 仓库里跑全量测试、归因失败用例并提交改动
root_cause: ""
solution: 四步流水：①长测试后台跑+结果与 EXIT_CODE 落盘日志轮询；②git index 锁失败时诊断陈旧 .git/index.lock 后删除；③失败用例用 HEAD 版本文件交换法归因（stash 栈是他人的，不碰），还原后 sha256 字节级校验；④git add 仅显式路径提交。
evidence: "evidence://v1/97ac9b2ff09290c28733bf5f83b516d53ce98d2cb3679df7d17077ef69bef488（后台+日志双通道启动）；evidence://v1/ddac9bec97d6f3f406154761800a5f32b0bf4bcb12c23cfa7e18e32aeff3128d（wait 终态）；evidence://v1/80eef84b819b4eaaf7817c5a4c239ca9edc77b7992d59e16f4ebcf7acf88d540（定向回归）；evidence://v1/5c459453d4b50d4503ed3b0181438881708f55fcca555f86cab6961965e0a44f（红测4项）"
tags: [shared-repo, pytest, git-index-lock, attribution, background-job]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T23:35:00.467831+08:00"
updated_at: "2026-10-28T23:35:00.467831+08:00"
---

在多会话共享的 mirror 仓库（如 llm-first-loop-mirror）做验证与提交时的四条纪律，均经 2026-10-28 任务实测：
1) 全量 pytest（>60s）用 execute_command(run_in_background=true)，命令内自带 `> .pytest_full.log 2>&1; echo "EXIT_CODE=$?" >> .pytest_full.log`，前台轮询日志取权威结果——EXIT_CODE 必须写进日志，job 终态 exit=0 只是 shell 包装码；该法对 job_id 手抄错误免疫。
2) git 报 "could not write index" 先查 .git/index.lock（0 字节、>1min 即陈旧可删）；确认无主进程再删。链式 worktree（.worktrees/*）用独立 index，删主仓锁不影响它们。
3) 失败归因不用 git stash（共享仓库的 stash 栈混有他人条目，push/pop 会误伤）：用文件交换法——`git show HEAD:<path> > .head_<n>` 暂存双方版本，cp 交换后跑测试，再 cp 还原并 shasum -a 256 对照 edit_file 回执的 artifact_sha256 做字节级校验。
4) 提交只 `git add <显式路径>`，绝不 add -A/-u：并发会话会实时产生未跟踪文件（experiences/、data/methods/、fixtures）。
基线事实：tests/unit/test_static_diagnostic_gate.py::test_unwritable_analyzer_cache_env_does_not_crash_main 在 HEAD 无改动基线即失败（0.50s 快速失败），非新改动引入。