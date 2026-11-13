---
title: 沙箱会话跑全量门禁的 TMPDIR 三层适配与审查准入漂移对策
scenario: 沙箱化 execute_command 会话内跑 ci_gate.sh 全量门禁（vitest/pytest tmp_path/BSD mktemp 三类临时目录语义互相冲突），以及 RULE-AI-28 审查准入在共享工作树上的切片外漂移
root_cause: ""
solution: 门禁命令统一用 TMPDIR=/private/tmp 前缀（与 env_channel 通道契约一致，沙箱可写）；shell 脚本临时文件一律显式 mktemp 模板；全量门禁前先定性新红（干净 worktree 对照），环境红修根因不进 shared ledger；审查 PASS 与命令执行之间不留时间窗
evidence: job-b3c76d0fc6e9440e88f9 exit=0（TMPDIR=/private/tmp 五段全绿）；对照实验：TMPDIR=工作区内 42 新红、TMPDIR=Caches 剩 5 红（env_channel+restore_prebackup）、TMPDIR=/private/tmp+mktemp 显式模板 30/30 绿；干净 HEAD worktree 复现同 5 红（定性环境红非代码红）
tags: [ci_gate, sandbox, TMPDIR, mktemp, review_admission, drift]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-12T21:33:31.820769+08:00"
updated_at: "2026-11-12T21:33:31.820769+08:00"
---

全量门禁 ci_gate.sh 在 execute_command 沙箱（仅允许写工作区与缓存目录）下的三层适配，全部实测验证：①vitest/Node 走 os.tmpdir()（吃 TMPDIR），但 TMPDIR 指进工作区内会破坏 pytest tmp_path 语义测试（not_cwd/scope_not_leaked 等 42 个红）——必须指到仓库外可写目录；②通道契约 test_real_sandbox_channel_predicates_hold 期望 tempfile.gettempdir()=='/private/tmp'，故正确姿势是 TMPDIR=/private/tmp（沙箱可写，验证过）；③BSD mktemp 无模板时走 confstr(DARWIN_USER_TEMP_DIR)=/var/folders，不吃 TMPDIR 环境变量——脚本内必须 mktemp "${TMPDIR:-/tmp}/xxx.XXXXXX" 显式模板（已修 scripts/restore_prebackup.sh 两处）。另外：RULE-AI-28 patch 级 PASS 的切片外漂移会被他 lane 的定时知识 flush 提交打穿（review_admission 绑定 HEAD+脏/未跟踪摘要），对策是 PASS 后立即以同串命令执行，或避开 flush 时窗重报。