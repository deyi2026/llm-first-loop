---
title: pgrep -f 文本模式等待循环会双重失效：幻匹配（模式原文出现在壳进程 argv）与永不匹配（venv python 已解析为绝对路径）
scenario: "跨脚本进程协调：等待/守护脚本用 pgrep -f \"文本模式\" 判断另一脚本启动的长命进程是否结束（macOS/Unix，sh -c 或 heredoc 包装启动）"
root_cause: pgrep -f 匹配的是命令行文本，不是进程身份；模式原文会出现在 heredoc 写入壳、自测试壳的 argv 里造成幻匹配；而真实目标进程的 .venv/bin/python 已符号链接解析为绝对系统路径，模式里的 worktree 前缀永不出现，造成永不匹配。等待循环因此既可能提前放行也可能永久挂起，两个方向都错。
solution: 等待长命进程结束不要用 pgrep -f 文本模式：①启动方直接 echo $! > pidfile，等待方轮询 kill -0 $(cat pidfile)；②或约定完成标记文件（如 touch DONE）+ 轮询产物特征（行数/EOF）；③确需 pgrep 时用 `pgrep -fl 模式` 列出 PID 人工核对命中者身份，排除持有模式原文的壳进程（heredoc 写入壳会常驻直到子进程结束）。已验证替代：DONE 标记+results.jsonl 行数轮询在双跑看护中稳定工作。
evidence: "evidence://v1/7b94299915bab7582151ded20dbd99491c65bac5e5348b06a6dd7f0af0122876（pgrep -fl 干净验证：唯一命中为 heredoc 壳 76469）；evidence://v1/5bc72dffdd6faa53e0b38fc2537a0b4ae239784927195f2316884ef31677f90c（双 chain 进程与两臂并行现场）；evidence://v1/6338434a81d342c923959185e024739dc38467451d826fdafd8d595caa27bf29（chain#2 清除+两臂行数无重复）"
tags: [pgrep, process-coordination, macos, background-jobs, shell, guard-script, m1-g2]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-15T20:34:22.734436+08:00"
updated_at: "2026-09-15T20:34:22.734436+08:00"
---

macOS pgrep -f 按整条命令行正则匹配，凡持有模式原文的进程都会命中：写入脚本的 heredoc sh 壳、`sh -c '…pgrep -f "模式"…'` 的父壳（pgrep 只排除自身不排除父壳）、以及残留的同名包装进程。M1-G2 双跑看护脚本 m1g2-chain.sh 用 `while pgrep -f "worktree/.venv/bin/python evals/pilot/run_pilot.py"` 等 baseline 结束，结果：(1) 两个现象——chain#1 在等壳进程出现前的检查窗口 pgrep 落空，提前 40 分钟启动 candidate（两臂并行）；chain#2 又一直"等到"含模式原文的 heredoc 壳 76469，若 baseline 真结束将再起第二个 candidate 写同一 results.jsonl 造成重复行。(2) 干净验证：pgrep -fl 列出命中 PID 只有 76469，真实 baseline 进程（解析后的 homebrew Python 路径）不含 worktree 路径前缀，永不匹配。修复：杀 chain#2，改用 DONE 标记文件+固定产物路径轮询协调。