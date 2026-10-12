---
title: 守卫复跑必须先清 LFL_/LLM_ 泄漏环境变量，且 pytest|tail 退出码不可信
scenario: 本地复验 CI 门禁（pytest/pyright/ruff）时，从 LFL 运行时会话通过 execute_command 后台跑全量测试套件
root_cause: 后台 execute_command 继承宿主会话 env（LFL_TOOL_WORKING_SET_GRACE_GROUPS/RECEIPTS/BATCH_CHARS、LLM_MODEL 等 14 个 LFL_/LLM_/MODEL_ 变量），改变了工具投影与 Web 配置判定行为；且 pytest|tail 的退出码被 tail 吞掉，done exit=0 不代表测试通过
solution: 守卫命令统一用 unset $(env | cut -d= -f1 | grep -E '^(LFL_|LLM_|MODEL_)' | tr '\n' ' ') 先清环境，并以输出内容（无 F/无 FAILED 汇总段/无 short test summary info）而非管道退出码判定通过；对可疑失败先在干净环境单文件复现定位是否环境泄漏（本例 GRACE=1 复现 4 FAILED、unset 后 10/10 过）
evidence: "job-8c67fce0（污染）vs job-a9c55b0d（干净）对照；evidence://v1/c8c3d934（409 复现）与 evidence://v1/424dc696（清环境后 7 passed）"
tags: [env-leak, pytest, execute_command, background-job, ci-parity, worktree-review]
source: {}
status: active
created_at: "2026-09-09T21:52:13.811630+08:00"
updated_at: "2026-09-09T21:52:13.811630+08:00"
---