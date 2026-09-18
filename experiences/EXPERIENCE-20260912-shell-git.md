---
title: 无时间戳 shell 历史与统一注入的 git 署名不能作为行为归因证据
scenario: "多 agent 环境中需要界定\"某提交/某行为由哪个会话/进程执行\"的治理审计"
root_cause: 将辅助证据（署名、无时间戳历史）当成了决定性证据
solution: "归因采用\"能力排除+窗口普查+谱系交叉\"三层：先证明目标窗口内哪些会话活跃（事件流水时间戳），再用 workdir/文件 mtime 谱系定位进程足迹，最后用悬空提交/分支拓扑确认 lineage。署名与无时间戳历史仅作方向性线索并显式标注\"不可作证据\"。"
evidence: ~/.zsh_history 无 EXTENDED_HISTORY 时间戳（0/2300 条）；git log --format='%an' 全部为 MCP Console；LFL 事件流普查窗口内唯一活跃会话与 wake 注册记录交叉闭合
tags: [forensics, multi-agent, git-attribution, shell-history, evidence-discipline]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-12T20:50:09.927218+08:00"
updated_at: "2026-09-12T20:50:09.927218+08:00"
---

证据：2,300 条 shell 历史无任何时间戳标记，无法用于证明某时间窗内"终端无操作"；git 提交署名 "MCP Console" 为 agent 工具链对全部提交的统一注入（本仓 shell identity 为 deyi2026，但当晚所有提交均署名 MCP Console，包括确认由 LFL 会话亲自执行的提交）。教训：跨进程/跨会话行为归因必须使用带时间戳的事件流水（event stream、invocation 日志、文件 mtime 谱系、进程快照）交叉验证；无时间戳的历史记录只能作辅助线索，不得作不在场证明或在场指控。