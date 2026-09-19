---
title: "research 树对 execute_command 全树只读（EPERM），可写区仅 /tmp 与 mirror：变异任务走\"staging+runbook\"模式"
scenario: "需要在用户项目树（如 /Users/yyj/Project/research）执行 mv/git worktree remove/写 README 等变异操作时，execute_command 直接报 \"Operation not permitted\"，而读操作全部正常，易被误判为权限位或文件 flags 问题。"
root_cause: ""
solution: 先用最小探针定界（touch 各候选路径：home/Project/research/mirror/tmp + git update-ref 探 .git 写），确认可写区=镜像工作区与 /tmp 后：产物（bundle/sha/抢救文件）先落 /tmp 再拷贝持久化到 mirror 下 staging 目录并校验；把全部变异步骤固化为带 sha256 自校验的一次粘贴 runbook.sh + README 索引草稿 + 证据日志，交由有写权限的终端执行；不使用子代理或旁路 shell 绕过边界。
evidence: "execute_command 回执：touch ~/与/Project/research 均失败、git update-ref \"unable to create directory for .git/refs/lfl/probe\" 失败、touch llm-first-loop-mirror 与 /tmp 成功；staging 产物 /Users/yyj/Project/llm-first-loop-mirror/staging-statebraid-20260914/（bundle sha256 -c 复核 OK 回执）；architecture_status：mirror stores writable=true。"
tags: [sandbox, execute_command, EPERM, staging-runbook, worktree, archive]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-14T22:45:41.496475+08:00"
updated_at: "2026-09-14T22:45:41.496475+08:00"
---

背景：2026-09-14 执行 StateBraid 归并任务时发现。事实：execute_command 子进程对 /Users/yyj 全树（含 ~/. 与 research/.git 内部 update-ref）写操作 EPERM；ls 无 flags、仅 com.apple.provenance；/tmp 与 /Users/yyj/Project/llm-first-loop-mirror/ 可写（touch 实测）。含义：用户项目树 research/ 对 shell 为只读边界，接近授权边界，禁止用子代理/旁路 shell 绕行。处置模式：①只读预检+产物全部先落 /tmp；②挑明写区（mirror）建 staging 目录持久化（bundle 拷贝后 shasum -c 复核）；③变异步骤写成带自校验的一次粘贴 runbook.sh（set -euo pipefail，worktree remove 默认→force 降级并记录原因），交用户终端执行或边界开放后接手；④索引/证据日志随 staging 一起备好。边界成因（沙箱 vs TCC 授予）未判明，勿假设稳定，下轮先复测 touch 再选路径。