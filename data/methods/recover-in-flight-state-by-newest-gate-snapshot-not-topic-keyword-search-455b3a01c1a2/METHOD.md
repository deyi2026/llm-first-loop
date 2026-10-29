---
method_id: recover-in-flight-state-by-newest-gate-snapshot-not-topic-keyword-search-455b3a01c1a2
name: recover-in-flight-state-by-newest-gate-snapshot-not-topic-keyword-search
description: 极简续跑（如'继续'）且 task_state 查询失败时，恢复在途状态的第一跳是 list_evidence 回执里按时间排序的最新条目：按工具类读它们——admission/gate 类 runtime snapshot 本身就是权威闸状态（pending/accepted/reviewer_failed 字段可直接分类下一步动作），最新 execute_command 揭示最后一个已验证事实。先水合这两条，再用只读 git delta 对齐树态；不要先造'上一轮在谈什么'的关键词去搜索（本集 3 次换词 miss）。pending 的闸用闸工具直接查询结算；reason=reviewer_failed 是基础设施失败，有界重发而非绕闸。仅当回执无'当前会话'作用域限定时，新近度水合才有跨任务污染风险，需先按命名 provenance 过滤。
aliases: 断点续跑先看最新回执别搜关键词, 状态丢了怎么恢复上一轮现场, 评审还在跑直接查闸别搜PASS, 继续指令无状态时的恢复顺序, 水合最新证据恢复现场
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:3e24aff2-8af5-497f-882a-a249bcc66acd:688:47ab5597b478fc8eab2f
evidence_refs: learning:learn:827685a7ab50
created_at: 2026-10-29T11:55:29.773593+08:00
updated_at: 2026-10-29T11:55:29.773593+08:00
---
## Trigger
极简续跑指令且 task_state/workspace 状态查询失败，但存在带时间戳、回执标注会话作用域的 Evidence 库（list_evidence 可用）

## Discriminator
list_evidence 最新 2~3 条的工具类与 acquired_at：admission/gate runtime snapshot 的机器可读状态字段（如 pending/review_still_running）即权威在途状态；search 回执标注'当前会话'⇒ 新近度=本任务，recency 水合不会被跨任务污染

## Short path
- task_state 失败后只保留一个未知量：刚才什么在途；直接 list_evidence 取最新条目，不先造话题关键词
- 按工具类选水合对象：最新 admission/gate snapshot + 最新 execute_command，各水合一次
- snapshot 显示 pending/review_still_running → 用闸工具直接查询结算该 review，不搜 'PASS/P0/P1' 类关键词
- 回执含 reviewer_failed/reviewer_unavailable → 判为基础设施失败：有界重发同一审查，不绕闸也不当内容结论处理
- 以只读 git delta（status/branch/log/diffstat 对权威远端）把证据态与树态对齐，然后继续原工作

## Stop conditions
- 在途闸状态与工作树状态均已由权威来源（闸回执/直接闸查询 + 只读 git 命令）确认且互相一致
- 发现 search 回执无会话作用域限定、或最新证据属于其他任务 → 停止 recency 水合，改按命名 provenance/作用域过滤

## Verification
- 水合 snapshot 的 target/command id 指向当前分支的动作，而非其他闸或旧轮次
- 直接闸查询的结果优先于关键词搜索命中的间接片段
- git delta 得到的提交范围与水合回执中已验证的区间一致

## Counterexamples
- 跨会话/共享 Evidence 库：最新条目可能属别的任务，recency 水合会误恢复现场，应先按作用域/命名引用过滤
- 多闸并行（push/merge/full_test）且最新 snapshot 属另一个闸：必须先对上 target/command id 再行动
- task_state 正常存在：跳过整个恢复流程直接续跑
- 库中最新条目只是普通文件读取、无闸语义：recency 只说明'读过什么'，pending 状态需从 git delta/schedule 证据另取
