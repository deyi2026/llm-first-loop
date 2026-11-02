---
method_id: is-done-closeout-partitions-surfaces-from-live-receipts-fdd13d4967b8
name: is-done-closeout-partitions-surfaces-from-live-receipts
description: 用户问"结束了吗/搞定了吗"时，"完成"是分面判据：合入+CI 全绿 ≠ 已生效。收口前用当前权威回执逐面核对——CI 逐 job 结论、run 列表最新性、部署回执的 desired git_head/generation 与修复提交对比、遗留屏障/滞后服务、工作树与产物前置条件——把回答分区为"已结束的面/尚未结束的面"，每条断言挂到回执证据行，未完成项合并为一个可立即执行的下步动作并请求确认；不凭上一轮心理模型直接答"结束了"。
aliases: 用户问结束了吗怎么答, CI全绿但没部署算不算完成, 收口回答分已做和未做, 修复合入了服务还没更新, 结束了吗先查部署落后
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:10484:eec114f5e723c1606cd7
evidence_refs: learning:learn:72694a48c371
created_at: 2026-11-02T21:34:36.373168+08:00
updated_at: 2026-11-02T21:34:36.373168+08:00
---
## Trigger
修复类长任务后用户以"结束了吗/完成了吗/搞定了吗"类问题收口，而任务横跨多个验证面（CI 门禁、部署/运行时服务、遗留屏障、工作树），任何一面的现状都可能与会话内最近的心理模型不一致

## Discriminator
部署/服务回执中的 desired git_head/generation 是否已包含本次修复提交（如 CI 绿的 run 对应新 head 而部署仍指旧 head）：这一 head/世代差在回答前即可机械对比，直接决定"已合入"与"已生效"是不是同一件事；run 列表同时确认该绿 run 是否为分支最新

## Short path
- 直查用户所指具名验证面的权威回执（如该 CI run 逐 job conclusion），钉死这一面的终态，不凭上轮记忆转述
- 查分支 run 列表确认刚才的绿就是最新、其后无更新的红 run（防拿旧绿当现状）
- 读部署/服务回执，把 desired git_head/generation 与修复提交对比：不一致即记为"未生效"面；同时登记屏障/滞后项（stale 服务、占位 barrier、audit_summary 中的 lag）
- 查工作树与构建产物状态，作为下一步动作的前置条件是否就绪
- 按"已结束的面/尚未结束的面"分区作答，每条断言指回本次回执行；把未完成项合并成一个前置条件已验证的单一执行提案（如 publish+restart），交用户裁决

## Stop conditions
- 每个相关验证面都有本次收口刚取得的权威回执，且其结论已写入回答
- 未完成项已逐条给出 delta 证据（head/generation 不匹配、barrier 记录等）并转化为一个可立即执行的下步提案，等待用户确认

## Verification
- 回答中每条"已成功"都能指回刚取得的回执行（run id、job 名、conclusion）
- 每条"未完成"都有明确差异证据而非记忆断言；下步提案的前置条件（干净树、产物在位）已被本次回执证实

## Counterexamples
- 任务只有一个验证面（用户只问 CI 本身红不红）→ 不必扩查部署/服务面，核对该面即收口
- 部署回执显示 desired head 已含全部修复且无遗留屏障 → 未完成分区为空，直接答"结束"并停止扩查
- 用户问的是某个具体子任务的验收 → 只核对该子任务的判据面，不做全域盘点
