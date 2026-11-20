---
title: CodeBuddy/WorkBuddy Agent Teams 与 git worktree 不是原生组合，隔离必须走多会话形态
scenario: 为 CodeBuddy CLI（workbuddy.ai/docs/cli）的 Agent Teams 设计并行开发编排的隔离与合并方案时
root_cause: ""
solution: "官方 Agent Teams 文档确认三点：① 成员 in-process 运行于同一终端（\"Members run in-process within the main terminal. All members share the same terminal window.\"），共享同一工作目录；② Best Practice 明示 \"Two members editing the same file simultaneously will overwrite each other.\"；③ git worktrees 出现在 Related Features 的 \"Manual Parallelism\"（手工多会话并行）下，不是 Agent Teams 的内建隔离。因此「Agent Teams + 每成员独立 worktree」不是产品原生组合：想要分支隔离就必须走多会话形态（每 worktree 一个独立 CodeBuddy Code 会话），协调靠人/脚本而非 lead；同终端形态只能用「文件所有权 + 越界检测 + CI 闸」收敛，不能靠分支。设计编排时先判定形态再谈机制，否则会给用户一个产品并不支持的组合预期。"
evidence: "官方文档逐条核对：https://www.workbuddy.ai/docs/cli/agent-teams（核对日期 2026-11-16），含 Execution Mode、Best Practice、Known Limitations、Related Features 四段原文；另核 https://www.workbuddy.ai/docs/cli/common-workflows 的 Manual Parallelism 段落。"
tags: [workbuddy, codebuddy, agent-teams, multi-agent, git-worktree, orchestration]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-16T21:55:03.616854+08:00"
updated_at: "2026-11-16T21:55:03.616854+08:00"
---