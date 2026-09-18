---
title: LFL 运行时 execute_command 环境注入 LFL_WORKSPACE_ROOT 致 git 相关单测环境性失败
scenario: 在 LFL 运行时内通过 execute_command 运行仓库 pytest 单测，凡依赖 git 相对 CWD 行为的用例（如 proc_version.workspace_dirty 系列）会出现与代码改动无关的失败，易被误判为回归。
root_cause: ""
solution: 回归判定前先做受控对照：env -u LFL_WORKSPACE_ROOT <venv>/bin/python -m pytest <case> 重跑；剔除后通过即可归因于运行时注入的环境变量（_git_command 的 -C $LFL_WORKSPACE_ROOT 使 git 偏离测试 tmp 仓库）。execute_command 非交互 shell PATH 无 python 时用绝对路径 .venv/bin/python。若要在运行时内获得可信全量结果，先剔除该变量再跑。
evidence: "对照实验证据：evidence://v1/82eca721afdb76cb8a99ccb5544d300487f72eec169b93e601ff1b0737ddc838（注入环境下失败）与 env -u LFL_WORKSPACE_ROOT + /Users/yyj/Project/llm-first-loop-mirror/.venv/bin/python 重跑通过（evidence://v1/667250eb65e6f864193b39f28487eb720b1e872404415e607612b57bebbb2756 同轮）；根因代码 src/llm_loop/introspection/proc_version.py:22-31（_source_workspace/_git_command 的 -C 注入）"
tags: [pytest, LFL_WORKSPACE_ROOT, environment-interference, regression-triage, proc_version]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-17T18:40:18.952635+08:00"
updated_at: "2026-09-17T18:40:18.952635+08:00"
---

在 LFL 运行时内用 execute_command 跑 pytest，tests/unit/test_proc_version.py::test_workspace_dirty_clean_and_dirty 稳定失败于 dirty 阶段断言（workspace_dirty() 返回 False）。根因：LFL 运行时向 execute_command shell 注入 LFL_WORKSPACE_ROOT（指向 .worktrees/deploy-main-19e253ed-20260917 部署 worktree），src/llm_loop/introspection/proc_version.py 的 _git_command 对所有 git 调用追加 -C $LFL_WORKSPACE_ROOT，使 workspace_dirty() 检查部署 worktree 而非测试 monkeypatch.chdir 的 tmp 仓库；部署 worktree 恒 clean → clean 断言碰巧通过、dirty 断言恒失败。对照实验：env -u LFL_WORKSPACE_ROOT 用 .venv/bin/python 绝对路径重跑该测试即通过。注意点：①凡依赖 git/CWD 相对行为的单测在 LFL 运行时内都会受此变量干扰；②execute_command 非交互 shell 里 PATH 无 python（command -v 为空），须用 .venv/bin/python 绝对路径；③判定"是否回归"先做 env -u 对照，勿把环境性失败计入改动回归。