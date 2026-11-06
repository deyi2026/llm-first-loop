---
title: 代码修改三陷阱：read 复用致臆想 API、editable venv 锚定错树、heredoc E6 阻断
scenario: 在 LFL mirror 仓库内做代码修改与验证：read_file 复用、editable venv 锚定、一次性脚本执行。
root_cause: ""
solution: 修改前 grep 核对签名；hunk 脚本逐段 assert 命中；验证走 pytest/ci_gate 通道；一次性脚本先落盘再 python3 -I；git http.* 配置改动前查合法范围并即时可回退。
evidence: "read_file ref_only 回执 + grep 对比；cd worktree 后 python -c 解析到 .releases/... 而 pytest 正常；三次 [安全硬阻断][E6_CATASTROPHIC_HARD]；postBuffer=1024 后 ls-remote 报 BUG: remote-curl.c:1529，unset 后恢复。"
tags: [read-file-reuse, editable-install, e6-guard, git-config, hunk-assert]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T14:06:00.505295+08:00"
updated_at: "2026-11-06T14:06:00.505295+08:00"
---

三个高危点全部实测踩中并有对策：1) read_file 对未变更文件会复用 evidence（回执 ref_only），我在推理中两次把 waiting.py/test_desktop_waiting.py 的 API 臆想成另一种形态（settle_ms 位置、WaitOutcome 字段），靠 grep 机械输出才发现；对策：动手前先 grep 签名与类定义行号，写 hunk 替换脚本时每个 old 必须带 assert old in src（本次救了 ≥3 次，包括 models.py ActOutcome 真实形态）。2) .venv 是 PEP660 editable 安装（metapath finder 锚到 .releases/7ae768519/src），直接 python 脚本 sys.path.insert(0,'.') 无效（还会测错代码树），而 pytest rootdir+pyproject pythonpath=['src'] 正常；对策：调试与验证一律走 pytest 上下文或 ci_gate.sh 的 PYTHONPATH 前置。3) E6 硬阻断 heredoc 直喂解释器——一次性脚本先 cat 落盘 /tmp 再 python3 -I 执行；顺带教训：git config http.postBuffer 设为 1024 会触发 git remote-curl BUG（LARGE_PACKET_MAX），导致所有 https 远端操作崩溃，改配置前先查该键的合法下限。