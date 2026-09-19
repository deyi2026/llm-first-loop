---
title: mirror 服务上线新代码：service_control restart 是记录绑定重启，需先造 qualified worktree 并推进 managed_service_deployment.json 代次
scenario: "LLM mirror（llm-first-loop-mirror）常驻 web/feishu 需要加载新提交的代码。service_control(action=restart) 是 desired-state 绑定的同码重启：按 managed_service_deployment.json 里既有 code_root 复活旧代码，只换 PID，永远不会拉取工作区新提交。此前据此误判\"重启即可上线\"。"
root_cause: ""
solution: "上线新代码的既有模式（今日 16:30 gen2→gen3 与本次 gen3→gen4 均按此成功）：qualified worktree + 改部署记录 + service_control 按新记录执行 + 指南 §6 逐项验收。部署资格必须包含反向检查 HEAD..main。"
evidence: "action svc-d695fc15db0f405898dcf90b04afc9d0 status=succeeded detail=\"restart_mirror rc=0\" gen4；data/audit/proc_versions.jsonl 尾两条 pid 98799(web)/98988(feishu) git_head=54441fd4 workspace_dirty=false；runtime_manifest.web/feishu.json llm_loop_module=.worktrees/deploy-merge-f85-20260917/src/llm_loop/__init__.py；HTTP 8903 auth/status=200 ui_v2=303 login=200；docs/LFL-restart-guide.md §4.2/§9.1 dist 复用例外"
tags: [deployment, mirror, service-control, worktree, merge-qualification, rollback]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-17T20:09:01.447127+08:00"
updated_at: "2026-09-17T20:09:01.447127+08:00"
---

完整流程（2026-09-17 gen3→gen4 实证）：1) 定目标 SHA：git rev-parse + 必查 git log HEAD..main 双向（本次拦下分支落后 main 43 提交、直接部署会回滚 1.25 万行的事故；信号：git diff --numstat 目标侧出现 0 增/大量删）；2) 独立 worktree 合并 main（git worktree add --detach，不动主检出脏树），小增量按 main 新风格移植（本次 config.py env_int/env_values）；3) 跑两侧测试（EVO 专项 + main config 套件，151 全绿）；4) webui/dist 机械复用：tracked webui tree 两端相同（git rev-parse SHA:webui）时从正服务 worktree 逐字节复制并记录文件数+树哈希前后值；5) 改 data/runtime/managed_service_deployment.json：generation+1、新 git_head、新 code_root、新 deployment_id（webui_artifact_sha256 因 dist 逐字节一致而沿用）；6) service_control restart expected_generation=新代次；7) 验收：action status=succeeded + proc_versions 新 PID@SHA + manifest llm_loop_module 路径 + curl /auth/status=200 且 /ui/v2/=303 且 /login=200 + 飞书心跳 connected。回滚=记录改回旧值+重启（旧 deploy worktree 保留勿删）。注意：验收 curl 端口以 manifest/resolver 为准（本机 8903，勿凭记忆写端口）。