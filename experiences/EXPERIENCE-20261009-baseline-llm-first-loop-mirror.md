---
title: 治理门 baseline 迁移与全量套件运行环境（llm-first-loop-mirror）
scenario: 在 llm-first-loop-mirror 中重构涉及 os.environ/os.getenv 的代码（如把进程管理从 mcp_client 迁到 mcp_transport），或在新 worktree 跑全量 unit 套件。
root_cause: ""
solution: 迁移已登记访问时同步更新 baseline 签名（同计数 1→1 替换，git diff 最小化：直接改 JSON 对应 key）；跑全量套件用 ../../.venv/bin/python3；worktree 下 identity guard 失败用干净基线 worktree 复跑归因。
evidence: "本次 P1-B 会话实证：迁移 mcp_client→mcp_transport 的 os.environ 访问后 gate 失败（新签名 mcp_transport.py|StdioTransport/start|bulk:raw|<all>）；baseline 同计数替换后 6/6 绿；test_runtime_identity_enforce 在 .worktrees/p0-mcp-adapter-20261009（commit c825ad890，无本次改动）同样失败。"
tags: [mcp, refactor, governance-gate, baseline, worktree, pytest]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-09T10:32:54.129730+08:00"
updated_at: "2026-10-09T10:32:54.129730+08:00"
---

本仓库 tests/unit/test_runtime_env_access_gate.py 以 per-signature（file|function|kind|key）JSON baseline（tests/fixtures/runtime_env_access_baseline.json）做单向棘轮：同签名计数只许降、新签名视为新增债务。重构把已登记访问（如 os.environ 子进程基底）移到新文件/新方法时，旧签名自然消失（迁移合法），但新签名必须显式写入 baseline（同计数替换），否则全量套件在治理门失败。另：全量 unit 套件必须用仓库 .venv/bin/python3 运行（系统 python3 缺 pypdf 等依赖）；tests/unit/test_runtime_identity_enforce.py::test_enforce_identity_match_ok 在任何 worktree 下都会失败（runtime identity 守卫比较运行时根），属环境固有项，可用「在干净 P0 提交 worktree 复跑同样失败」归因排除。