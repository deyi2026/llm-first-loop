---
method_id: gated-action-timeout-verify-target-reauthorize-then-background-retry-7b0b678f2e0e
name: gated-action-timeout-verify-target-reauthorize-then-background-retry
description: 由一次性资格放行的受保护动作（本集为经独立审查 PASS 后的 git push）在前台工具超时处中断时：超时回执不是动作终态。先在权威目标面对账（ls-remote 比对远端/本地 head）判断动作是否落地；资格已被消费时不要原样重试，按 blocked 回执逐字点名的再授权通道（review_admission start/status，可能命中同内容 PASS 复用窗）重建资格；再以单条命令转入不受前台时限约束的后台执行等终态。受保护命令必须单条提交——重定向/分号/echo 包装会被拆段拦截。
aliases: 推送超时资格被扣了, 超时不算失败先查远端, 一次性授权撞时限, 慢链路 git push 被拦, 别拿分号重定向包受审命令, 复用窗怎么兑现
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a6989bff-e814-43eb-9f8a-a24f42790dd9:1215:9d0ac061c66c3890216e
evidence_refs: learning:learn:37a9d3777786
created_at: 2026-11-06T07:56:59.813557+08:00
updated_at: 2026-11-06T07:56:59.813557+08:00
---
## Trigger
受保护/涉权动作（需一次性资格或独立审查放行，如推送类写操作）的执行回执为工具超时，或随后 blocked 回执称"不存在覆盖当前产物的有效审查资格"；且环境对前台命令有时限（如 60s）而对后台 job 无此限。

## Discriminator
超时回执只证明"调用未在时限内返回"，无法区分"动作未生效"与"仍在飞行/已落地"；而 blocked 回执已逐字给出恢复通道（start 发起审查→status 核验 PASS→同一目标重试）。首次超时后一条权威目标面查询即可裁决：远端 head 未变＝动作未落地且资格已被消费。

## Short path
- 受保护动作从一开始就以单条命令提交（不带重定向/分号/echo 拼接），避免 compound 拆段拦截浪费一轮资格
- 前台超时后，第一个未知量是"动作是否落地"：一条权威目标面对账（比对远端 head 与本地 head），不先重试
- 远端未动＝资格已被消费且无效果 → 按 blocked 回执处方走再授权通道发起资格请求；回执 cached_pass=true（同内容 PASS 复用窗）即已持有有效资格，不必强开新审查
- 以同一目标、单条命令转后台执行（不受前台时限约束），wait/job_output 等到终态；连续多次 wait 超时后按 repeat_guard 提示记账并降低轮询密度，穿插收尾工作而非机械递减盲等
- 以 job 终态 exit=0 且输出含 old..new range（与远端 head 一致）确认落地，退出恢复分支

## Stop conditions
- 权威目标面显示目标内容已落地（远端 head=本地 head，或 job 终态 exit=0 且 range 更新一致）
- 再授权回执 PASS/有效资格已覆盖同一候选产物与目标，且重试被受理进入执行
- 对账发现远端已推进到本地 head：动作实际早已成功，停止一切重试转登记（再推会 non-fast-forward）

## Verification
- 推送输出中的 old..new range 与权威远端面查询到的 head 完全一致
- 资格回执（含 cached_pass 复用）的 candidate 摘要/目标与实际执行的动作产物一致

## Counterexamples
- 非受保护、幂等的读/查询操作超时：直接重试即可，无需目标面对账与再授权
- 资格可再生且动作幂等（无一次性消费）：超时后原样重试是合法首选项，不必先走再授权
- 宿主要求受保护动作前台交互确认、禁止后台执行：不能转后台，应缩小单次变更集（分批）降低超时概率
- 目标面显示动作已落地：任何再授权加重试都多余且可能造成 non-fast-forward，正确动作是登记成功并停止
- 快链路/无前台时限环境：恢复分支不触发，单次前台执行即终态
