---
title: desired deployment 从 worktree publish 会被 knowledge-health preflight 以 legacy_experience_divergence 隔离，restart 必 fail-closed
scenario: "managed-service 部署线：desired deployment 从 .worktrees/xxx publish（code_root=worktree）后，restart worker 的 knowledge-health preflight 以 legacy_experience_divergence 隔离（quarantined, writes_enabled=false）并拒绝停止现有服务，restart rc=1 fail-closed；live 服务保持旧代际。"
root_cause: 从 worktree publish desired deployment 时，code_root 指向 worktree，worktree 内 git 检出的 experiences/ 快照与共享 data 推断出的正仓 experiences/（含运行期新增记录，248→249）发生 legacy_experience_divergence，knowledge-health 判定 quarantined 并 fail-closed 拒绝重启。CLI publish/worker 又是 operator-only，模型会话无法自行改 desired。
solution: desired deployment 一律从 runtime root（正仓）publish：先把正仓 fast-forward 到目标 commit（确认与 untracked 无重叠后 git merge --ff-only），在正仓重建 webui dist，再从正仓根 publish（expected-generation=当前 desired 代际）并 verify；确认 verify ok 后才发且仅发一次 restart-all。不要从带独立 experiences/docs 树的 worktree publish desired；若已被 worktree desired 卡住，由有 operator 权限的会话从正仓 republish 覆盖。
evidence: "data/runtime/service-control-actions/svc-7cd6ffaf6cff4e2db5f945f41db45115.json (status=failed, detail=restart_mirror rc=1); data/service-control-worker.log 00:58:00 行 \"✗ Knowledge health preflight FAILED；拒绝停止现有服务\" 且 binding.reasons=[\"legacy_experience_divergence\"]; data/runtime/service-control-actions/svc-579554e86ab44fd3b64038655b8912b8.json (failed: desired advanced while waiting)"
tags: [service-control, managed-deployment, knowledge-health, worktree, restart, fail-closed]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T01:07:46.736485+08:00"
updated_at: "2026-09-19T01:07:46.736485+08:00"
---

2026-09-19 00:57-00:58 svc-7cd6ffaf（restart web, gen42）在 waiting→执行阶段失败：restart worker 的 Knowledge health preflight 计算出 binding：experiences_dir=正仓 experiences（249 条，data_dir_inferred）而 legacy_experiences_dir=gen42 worktree 自带的 experiences（git HEAD 快照），二者不一致 → status=quarantined / writes_enabled=false → "拒绝停止现有服务"，rc=1，未动 live 进程（fail-closed 正确）。同窗口 svc-579554e8 因 desired 已从 41 前进到 42 被干净拒绝。结论：managed deployment 的 code_root 不要指向带独立 experiences/docs 的 worktree；desired 应从 runtime root（正仓）publish。修复路径：正仓 ff 到目标 commit（06552a114→1103a7493 已做）→ 正仓 npm run build → 正仓 publish --expected-generation 42 → verify ok → 再发唯一一次 restart。CLI publish/worker 被 operator control-plane hook 拦截（模型会话不可直接跑），需 MCP Console/操作员会话执行 publish。