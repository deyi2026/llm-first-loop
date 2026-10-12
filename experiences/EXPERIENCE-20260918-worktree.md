---
title: 共享 worktree 提交必须显式路径 + 提交前核对他人并发改动
scenario: 共享 git worktree 的多会话环境（llm-first-loop-mirror 主仓，多个 AI 会话 + MCP Console 并发工作），需要提交自己改动并重启服务
root_cause: ""
solution: commit 前先 git log -1 核对 HEAD 是否被他人推进、git status 核对是否有非自己的修改文件；只对明确属于本任务的文件 git add <显式路径>；他人 WIP（如 governor.py）不碰不提交；提交后 HEAD 若与部署清单 git_head 不一致属正常，重启时 preflight 重绑代次
evidence: "evidence://v1/3659d4c0e260343bb9ee5a1045f106456d12081dfded083888b773d7049507bf（git add -A 超时回执）；evidence://v1/c840a08b6077c23f0fa394ada6013ee9e7279e5ba34b489f68090422a632c7b2（HEAD 0cdd8bbb3 为 MCP Console 22:46:50 提交 + governor.py 61行 WIP diff）；evidence://v1/d4668f855797b31365e12d1459e9b42d6d06fd2cb22760c05005b6e5d3b4b31f（evolution_complete 拒绝 accepted 状态回执）"
tags: [git, multi-agent, shared-worktree, commit-hygiene, service-restart]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-18T23:03:47.577391+08:00"
updated_at: "2026-09-18T23:03:47.577391+08:00"
---

在 llm-first-loop-mirror 主仓工作时：1) 另一会话（MCP Console）可能并发提交（HEAD 从 ce7aee491 → 0cdd8bbb3）并留下未提交 WIP（governor.py）；2) git add -A 会把 .formal-v1/ 等大量未跟踪目录暂存，导致 commit 钩子超时；3) 提交必须显式列文件路径，绝不 add -A；4) 重启服务前查 worktree 是否有他人 WIP——重启会把未提交代码载入新进程；5) 演进建议在 accepted 状态时完成登记走 CLI `.venv/bin/python -m llm_loop.cli evolve-complete <id> "说明"`，AI 工具 evolution_complete 仅接受 executing 状态。