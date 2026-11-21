---
title: spawn_subagent 审稿：模型名须精确到 registry 规范名，5 秒超时不等于失败
scenario: 定时推广班次发布前，用 spawn_subagent 起独立子代理审事实与合规，且用户指定了审稿子代理也必须用某个特定模型（如 minimax/MiniMax-M3.1-Flash）。
root_cause: ""
solution: "用 registry 精确模型名 minimax/MiniMax-M3.1-Flash 调用 spawn_subagent（requires 只给只读工具 + write_scope=deny，max_rounds 25 左右），5 秒超时先当\"未判定\"重试并用 subagent_topology(parent_id=...) 确认是否已建 child，而不是立即改参数。"
evidence: "docs/promotion/STATUS-20261118-daily97.md 第九节教训第 1 条；spawn_subagent 失败回执 child_model_unavailable:ValueError:provider 'minimax' 不存在模型 'MiniMax-M3.1-Fash'（规范候选: MiniMax-M3.1-Flash 等）；审稿子代理 child_id=subagent_58b9e6be422c 最终以 minimax/MiniMax-M3.1-Flash 成功返回 FAIL(2 P1/6 P2) 结论。"
tags: [spawn_subagent, 模型路由, 审稿子代理, 超时, 头条推广, 规则AI-28]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-18T13:47:17.469875+08:00"
updated_at: "2026-11-18T13:47:17.469875+08:00"
---

场景：LFL 定时推广班次要用独立子代理做发布前内容审稿。三个坑：
1) spawn_subagent 的 model 必须精确到 registry 规范名。写 `MiniMax-M3.1-Fash`（少一个 l）会被拒，回执形如 "child_model_unavailable:ValueError:provider 'minimax' 不存在模型 'MiniMax-M3.1-Fash'（规范候选: MiniMax-M3, MiniMax-M3.1-Flash, MiniMax-M3.1-Flash-Preview）"。正确写法是 provider 限定形式 `minimax/MiniMax-M3.1-Flash`。
2) spawn_subagent 工具本身有 5 秒超时。本班连续两次调用都返回 timeout，但第一次其实参数是对的——超时不代表失败也不代表参数错，不要据此改参数。真正的错误要靠一次"故意带错模型名"的调用暴露出来，否则会一直在超时里打转。
3) 审稿子代理的 requires 建议给 write_scope=deny + 只读工具集（read_file/search_files/execute_command），fs_isolation=true 会显著拉长启动耗时（git worktree 创建），对只读审稿不必要。
适用范围：任何"发布前独立审查子代理"任务。