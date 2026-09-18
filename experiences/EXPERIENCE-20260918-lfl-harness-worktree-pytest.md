---
title: LFL harness 环境变量泄漏导致 worktree pytest 假失败
scenario: 在 /private/tmp worktree 里用 mirror venv 跑 llm-first-loop pytest 时出现 runtime_root 指向 mirror 的 identity/manifest 类测试失败
root_cause: harness 运行时环境变量泄漏进被测子进程，覆盖了测试默认的 workspace→runtime_root 推导路径
solution: 跑 pytest 前显式 env -u LFL_RUNTIME_ROOT -u LFL_WORKSPACE_ROOT -u LFL_ENV_FILE -u LFL_ROUTE；再在父提交复跑做归因，避免把环境污染误判为代码回归
evidence: "evidence://v1/8ac2f26d78cedce32cd9cc85ac046145cfd3c59daee57586c9598fd9de431414（env 泄漏实测）；evidence://v1/0746f334bdfaf48f4f44e2c6fe270353173dd380df4424b3920ed8fb3159c547（清变量后 2/3 转绿）"
tags: [pytest, env-pollution, worktree, LFL_RUNTIME_ROOT, false-failure]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-18T09:48:24.219485+08:00"
updated_at: "2026-09-18T09:48:24.219485+08:00"
---

LFL harness 自身 shell 持有 LFL_RUNTIME_ROOT/LFL_WORKSPACE_ROOT/LFL_ENV_FILE/LFL_ROUTE 等变量，execute_command 子进程会继承，导致 pytest 中依赖 workspace 推导 runtime_root 的测试（identity_enforce/launch manifest 等）false-fail。修正：pytest 前加 env -u LFL_RUNTIME_ROOT -u LFL_WORKSPACE_ROOT -u LFL_ENV_FILE -u LFL_ROUTE（2026-09-18 PR #28 排障实证：清变量后 3 失败变 1，剩余 1 处为真实基线未登记）。