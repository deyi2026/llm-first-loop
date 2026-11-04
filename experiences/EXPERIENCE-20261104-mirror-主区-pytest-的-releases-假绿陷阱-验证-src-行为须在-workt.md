---
title: mirror 主区 pytest 的 .releases 假绿陷阱：验证 src 行为须在 worktree（PYTHONPATH=src）跑，stash 对照分离既有红
scenario: llm-first-loop-mirror 仓库：在主工作区验证 src 行为相关的 guard/集成测试（函数行数棘轮、import 环、phase4 runner 集成等）
root_cause: ""
solution: "需要真实解析本树 src 时，在 worktree 中以 PYTHONPATH=src + 主区 .venv 解释器跑（ci_gate.sh 已内建该回退）；主区结果仅作线索。归属不明时用 git stash 对照法分离变量；对 \".venv 存在性\" 敏感的 env_preflight 类测试回主区对照判别环境性假红。uv run --no-sync 勿在新 worktree 用（会静默建空 .venv）。"
evidence: "evidence://v1/78fd1c9c42c2c9de3046c4c8fd8e11e2352be31485769b560f2ac90bbf248375（主区3绿）+ evidence://v1/a601c478ce7322e83430dcfacea3157fd521f3ead6ca179c6216a6d9706cd52c（worktree ci_gate 3红名单）+ evidence://v1/d37d7e9b2722（.releases 解析）"
tags: [ci_gate, worktree, venv, 假绿, guard, 测试环境]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-04T00:30:38.717081+08:00"
updated_at: "2026-11-04T00:30:38.717081+08:00"
supersedes: [EXPERIENCE-20261018-pythonpath-陷阱是不对称的-pytest-跑活跃树-裸-python-跑-releases]
---

在 llm-first-loop-mirror 仓库验证 src 行为相关测试（guard/棘轮/环检测/phase4 集成）时，主区 shell 直接跑 pytest 会因 .venv 的 editable 指向 .releases/<旧提交> 副本而测旧代码（pyproject [tool.pytest.ini_options] 上方注释已警告）；主区 guard"绿"可能是假绿。实证：2026-11-04，74b9e7ee9（claims 线）提交时 src 函数行数/环超基线（task_store.compute_frontier 124→127、config.load_settings 376>370、subagent/runner.start 406>399、新环 task_claim<->task_store、l1l2 window_hours 24→0），主区跑 3 guard 全绿（假绿），worktree（PYTHONPATH=src 解析本树）跑即红，直到 claims 线 push 审查时才暴露收尾。判别法：(1) worktree + PYTHONPATH=src 跑（ci_gate.sh 自带该回退）；(2) 归属不确定时 git stash 改动后同环境重跑，红仍在=既有债务；(3) env_preflight 类对".venv 存在性"敏感的测试在 worktree（无自身 .venv）会环境性假红，回主区对照即可判别。另：uv run --no-sync 在新 worktree 会静默创建空 .venv 导致 pytest 缺失——删掉空 venv 后直接用主区 .venv 解释器。