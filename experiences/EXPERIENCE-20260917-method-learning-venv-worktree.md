---
title: Method Learning 启用：双层开关与 venv→worktree 导入陷阱
scenario: 给 llm-first-loop-mirror 常驻服务启用/修改默认行为（如 Method Learning、新配置默认值）时，改了主镜像 src + README + 测试全绿，但重启后运行时行为不变。
root_cause: ""
solution: "运行时行为变更优先走 PROJECT_DIR/.env 显式变量（对旧代码同样生效）；代码默认值变更需走 qualified worktree 上线流程（commit → merge worktree → 代次推进 → service_control），且注意与并行部署会话协调。验证启用不要看日志 INFO 行（root logger 未配置时会吞掉\"Learning Plane 已装配\"），要看 durable 产物：data/sessions/learning/journal.jsonl 是否出现并增长。"
evidence: "data/sessions/learning/journal.jsonl（queued=1, admitted=16, requeued=16, reason=resource_authority_changed）；.venv/lib/python3.13/site-packages/__editable__.llm_first_loop-0.6.8.pth → worktree src；.env:227/229（METHOD_REFLECTION_MODE=auto + LEARNING_PLANE_ENABLED=1）；src/llm_loop/factory.py:1462（settings.learning_plane_enabled 装配点）；data/methods/lfl-mirror-qualified-worktree-33ba78f2f2e7/METHOD.md（并行会话的上线流程方法卡，佐证 restart 不拉新码）"
tags: [method-learning, deployment, worktree, venv-editable, enablement]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-17T20:22:42.517809+08:00"
updated_at: "2026-09-17T20:22:42.517809+08:00"
---

背景：Method Learning 默认双开关导致 5 天零产出（.env 只有 METHOD_REFLECTION_MODE=auto，LEARNING_PLANE_ENABLED 未设，journal=None 直接 return）。启用后发现：(1) 两开关必须同时开；(2) venv 的 __editable__.pth 指向 .worktrees/deploy-merge-f85-20260917/src，所有 .venv/bin/python 进程（含常驻 web/feishu）import 的是 worktree 代码，主镜像 src 的代码默认改动对运行时不生效——.env 显式变量才立即可达运行时；(3) service_control restart 按既有 code_root 复活，不拉新码，新代码上线需 qualified worktree 流程。验证：重启后 data/sessions/learning/journal.jsonl 出现（20:13 创建、持续增长），queued=1/admitted=16/requeued=16（前台让位循环，属设计内）。注意：pytest 经 tests/conftest.py:79 把项目根插 sys.path 前端，测的是主镜像源码——测试绿 ≠ 运行时吃到改动。