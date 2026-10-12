---
title: "worktree 冻结隔离会丢 .env：评测臂需显式注入运行时配置并加\"到达模型\"熔断"
scenario: "用 git worktree --detach 冻结被测 agent 代码以保证评测隔离（AgentPilot v1.1 redo，freeze 1437be74）。.env 属 gitignore 未跟踪文件，worktree 不携带；runner 以 env=dict(os.environ) 启动子进程且父 shell 未导出 LLM_API_KEY，导致 LFL 臂 36/36 全部在 0.1s 内以\"缺少必填环境变量 LLM_API_KEY\"INFRA_FAIL，整个 108 项 redo 的 LFL 列报废。机械 gate（冻结树 sha/行数/plan_sha）全部无感知。"
root_cause: .env 被 gitignore，git worktree --detach 不迁移未跟踪文件；runner env=dict(os.environ) 而父进程未导出这些变量；gate 只验代码/行数/sha，不验臂是否到达模型
solution: 代码冻结必须连同运行时配置一起迁移或显式注入：优先在矩阵父进程 set -a; source .env; set +a（runner 已继承 os.environ），或在 runner 内显式组装 env；不动冻结树本体。并在 gate/runner 增加早期熔断：任一臂连续出现亚秒级 INFRA_FAIL（如 3 连 dur<1s 且 ok_run=false）即中止矩阵并报警，而非烧完 36 个槽位后才发现。
evidence: "/private/tmp/agentpilot-v11-redo-20260912/results.jsonl（36×lfl INFRA_FAIL, dur=0.1s, stderr=缺少 LLM_API_KEY）；/private/tmp/lfl-freeze-1437be74 仅含 .env.example；本仓 ./.env 含 LLM_API_KEY 等键"
tags: [agentpilot, frozen-worktree, env-injection, infra-fail, early-abort]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-12T23:10:30.587279+08:00"
updated_at: "2026-09-12T23:10:30.587279+08:00"
---