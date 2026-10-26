---
title: 在 LFL 会话内跑 llm-first-loop 测试：剥部署环境变量并用 .venv 解释器
scenario: 在 LFL 自身运行时的子 shell 中对 llm-first-loop 仓库跑单元测试（agent dogfooding / 审查任务）
root_cause: ""
solution: "执行模板：cd 仓库 && unset LFL_WORKSPACE_ROOT LFL_DATA_DIR LFL_RUNTIME_ROOT LFL_ENV_FILE LFL_FLEET_WORKSPACE_ROOT && .venv/bin/python -m pytest <targets> -q。出现 \"Workspace is not registered\" 或 Crypto 收集错误时先检查解释器与 ambient 变量，不要当作代码回归。"
evidence: "evidence://v1/1f231397688e53158201122f155b79b676b6ebc5f9a1b0b815b020a598bb6dc2（8 失败清单）；evidence://v1/c76bdf70e5cc89e0ff71aa13dc102c32db67db6ce17f18433b3bfb37401a71f6f（180 passed）；evidence://v1/b45a087d8cbf2ba7939e2a46bdc8f0eab946cd5a58b4334975d61a33a80f40bb（1484 passed）；evidence://v1/71ae5a4e9dcb41a6b87e9e777e92cf3737e157481f2f335d410ac34410de99bb（workspace 解析到 .releases 的复现输出）"
tags: [pytest, 环境隔离, LFL_WORKSPACE_ROOT, dogfooding, 终端CLI]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-20T20:38:28.005150+08:00"
updated_at: "2026-10-20T20:38:28.005150+08:00"
supersedes: [EXPERIENCE-20260917-lfl-execute-command-lfl-workspace-root-git, EXPERIENCE-20260909-lfl-shell-pytest-web-auth-require-web-origin-allow, EXPERIENCE-20260918-lfl-harness-worktree-pytest]
---

在 LFL 运行时（web/execute_command）派生的 shell 里执行仓库 pytest：1) 必须用 .venv/bin/python 或 uv run（裸 PATH 的 python3 缺 pycryptodome，32 个 web 测试文件收集即 ModuleNotFoundError: Crypto）；2) 必须先 unset LFL_WORKSPACE_ROOT（还有 LFL_DATA_DIR/LFL_RUNTIME_ROOT/LFL_ENV_FILE/LFL_FLEET_WORKSPACE_ROOT），否则 test_terminal_cli.py 8 个用例因 query_context 把 ambient LFL_WORKSPACE_ROOT 当显式 workspace（queries.py:87/357）而确定性失败 "Workspace is not registered"。验证：带环境 8 failed；剥离后 terminal 7 文件 180 passed、大切片 1484 passed（2026-10-20，llm-first-loop-mirror @610df0621）。conftest 部署环境隔离 batch1-4 漏了 LFL_WORKSPACE_ROOT。