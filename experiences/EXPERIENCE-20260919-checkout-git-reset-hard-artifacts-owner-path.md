---
title: 共享 checkout 多会话下 git reset --hard 抹掉并行会话未提交编辑；用 artifacts 记录按 owner+path 恢复
scenario: 共享主 checkout 的多会话环境（llm-first-loop-mirror 同时有 console/终端多会话），需要 git 同步（pull/reset/switch）或任何会改写 tracked 文件的批量操作时。
root_cause: 同一 workspace 多会话共享单一主检出，git 写操作（reset --hard / switch / checkout）按单会话心智使用，未先核对 M 文件归属；且后台 job 完成不唤醒，依赖前台 sleep 轮询拉长了无人值守窗口。
solution: 同步前：git status 出现非本会话的 M tracked 文件 → 先 event_stream(scope=workspace) 或 data/artifacts/records 归属判断；有并行编辑在途时改用只读 fetch + 显式 worktree，不在主检出 reset --hard。已损毁时：按 owner_session_id+relative_path 取最新 file_replace artifact 校验 sha 回写恢复。
evidence: "恢复脚本输出（本会话 14:3x）：session 855926d8 file-replace records: 39；RESTORED 11 个文件（tool_execution_journal.py/coordinator.py/runner.py/codearts_dispatch.py/dsh_task.py/edit_file.py/execute_command.py/workflow.py + tests fleet×3）；git status 恢复显示 12 个 M tracked 文件与 reset 前一致；记录示例 data/artifacts/records/dc2d03211f13f0ed8f600101ee528d8c/10b914d35f434b74a387255a2192e299.json（owner_session_id=855926d8…, relative_path=src/llm_loop/tools/builtin/dsh_task.py, sha256=f32feeab…, blob 校验通过）。"
tags: [git, multi-session, workspace, reset-hard, artifact-recovery, llm-first-loop-mirror]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T14:31:01.547225+08:00"
updated_at: "2026-09-19T14:31:01.547225+08:00"
supersedes: [EXPERIENCE-20260918-worktree, EXPERIENCE-20260919-checkout-main-git-branch-show-current-main-worktre]
---

2026-09-19 14:27：会话 863879fe 在 llm-first-loop-mirror 主检出上执行 git reset --hard 同步 release 分支，抹掉了并行会话 855926d8 未提交的 12 个文件编辑（正在进行的 fleet/dsh_task 工作）。同一 workspace 的多个活跃会话共享同一个工作树；git status 里出现的非本会话 M 文件不是垃圾，是并行工作。恢复：data/artifacts/records/*/<artifact_id>.json 含 owner_session_id / relative_path / effect_kind=file_replace / sha256 / created_at；blob 在 data/artifacts/blobs/sha256/<前2位>/<sha>.blob；按 (owner_session_id, relative_path) 取 created_at 最新记录、校验 sha 后回写文件即精确恢复（实测 11 文件恢复成功，第 12 个 reset 后已被原会话重写、跳过）。search_records kind=file_effect 查不到其它会话记录时，直接扫 data/artifacts/records/ 目录。