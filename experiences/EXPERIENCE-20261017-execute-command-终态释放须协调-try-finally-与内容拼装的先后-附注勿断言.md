---
title: execute_command 终态释放须协调 try/finally 与内容拼装的先后（附注勿断言泛前缀）
scenario: execute_command 增加 isolation=true 命令级 worktree 隔离（EVO-20261016-96abc163 实施中）：工具内需在命令终态（正常/超时/拒绝/OSError）恰好一次释放隔离树并把 ReleaseReport 附注并入回执。
root_cause: ""
solution: "1) 插桩（monkeypatch prepare/release 记录调用序列+is_dir 状态）复现，确认 release 被调两次且第二次得 missing；2) 读源码确认内容拼装在 try/finally 之后；3) 改为 finally 确定性释放+置位+附注暂存（wt_note），内容路径 _wt_note_in 只消费暂存或内联路径现场释放，共享 nonlocal 标志；4) 单测断言升级为精确终态文案；5) 真实仓库双冒烟（干净→\"已清理隔离树（干净）\"+树删；脏→\"隔离树保留（N 个文件，HEAD=…）\"+树留）。"
evidence: "tests/unit/test_execute_command_isolation.py 9 例全过（精确终态文案断言）；真实仓库冒烟回执：clean→[worktree] 已清理隔离树（干净）且树消失，dirty→[worktree] 隔离树保留（1 个未提交文件，HEAD=7ec443b…）；commit 41f500ecb。"
tags: [execute_command, worktree-isolation, try-finally-ordering, one-shot-release, test-assertion-strength, evolution-policy]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-17T08:14:52.474004+08:00"
updated_at: "2026-10-17T08:14:52.474004+08:00"
---

在 src/llm_loop/tools/builtin/execute_command.py 中为终态回执加资源释放时，必须先看清结构：sync 命令的回执内容拼装（summary/gate/content join 与最终 return）位于大 try/except/finally 块**之后**。若在 finally 放"兜底释放"、又在内容路径放"释放+附注"，执行顺序会是 finally 先释放（无附注、不清一次性标志）→ 内容路径二次 release_worktree → ReleaseReport.state=missing → 回执附注变成"树不存在"。正确模式：finally 与内容路径共享同一组一次性标志（wt_released/wt_note 暂存），finally 释放时置位并暂存附注，_wt_note_in 优先消费暂存附注——release 恰好一次、附注恰好一条。单测教训：对回执附注只断言泛前缀（如 "[worktree]"）会把"树不存在"漏成绿；须断言精确终态文案（"已清理隔离树（干净）"/"隔离树保留"）。另：演进执行面还有一条政策事实——EVOLVE_LOCAL_EXEC=0（2026-10-14 用户裁决仅建议档）时，人工 exec_override 只越过边界门、不越过级别门，store 停留 accepted，状态推进仍属人工通道。