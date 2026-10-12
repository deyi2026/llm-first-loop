---
title: Worktree 全量门禁环境陷阱：ambient env 泄漏 + enforce_identity 要求 venv 在 workspace 内
scenario: 在 .worktrees/* 隔离 worktree 里对 committed candidate 跑 LFL 规范门禁（scripts/ci_gate.sh：ruff+env-pin+pyright+tier0+全量 xdist pytest）
root_cause: ""
solution: ① 净化环境启动：env -u PYTHONPATH -u LFL_RUNTIME_ROOT bash scripts/ci_gate.sh；② 先 cp -Rc 主仓 .venv 到 worktree/.venv（APFS 克隆），使 enforce_identity 的 venv-in-workspace 判定成立；③ 永不在有 live 服务的主检出上切分支跑门禁。
evidence: /tmp/ci_gate_prebaseline.log（泄漏环境：identity 红）vs /tmp/ci_gate_prebaseline2.log（净化环境+克隆 venv：全链 PASS）；/tmp/ci_gate_fleet_slice.log（同法复用）；service_control status 显示 3 个 live 进程跑在主仓 .venv
tags: [ci_gate, worktree, identity, venv, gate]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-19T08:52:37.667979+08:00"
updated_at: "2026-09-19T08:52:37.667979+08:00"
---

在 LFL 仓库的隔离 worktree 上跑 ci_gate.sh 全量门禁时，两个环境事实会导致 identity 测试假红：
1. agent 会话环境里泄漏的 LFL_RUNTIME_ROOT 与 PYTHONPATH（指向主仓）会覆盖 runtime_root 判定与 sys.path 尾部——必须 `env -u PYTHONPATH -u LFL_RUNTIME_ROOT bash scripts/ci_gate.sh`。
2. runtime/identity.py 的 enforce_identity 要求 sys.prefix（venv 解析路径）位于 workspace 内部；共享主仓 .venv 的 worktree 永远不满足。用 `cp -Rc <主仓>/.venv <worktree>/.venv`（APFS clone，秒级、零实际磁盘开销）解决，然后 ci_gate.sh 自动优先使用 worktree 内 venv。
另外：主仓检出跑着 live 服务（web/feishu/learning）时，绝不能为跑门禁而 detach/切换主仓分支——门禁一律在 worktree 内做。