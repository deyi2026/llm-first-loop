---
method_id: trust-authoritative-receipt-then-single-right-sized-poll-95a9fc19d474
name: trust-authoritative-receipt-then-single-right-sized-poll
description: 控制命令（publish/dispatch 受理）返回的权威回执若已含下一步所需全部字段（generation、git_head、action_id、校验和），直接把回执当作已解决的 provenance 推进下一个依赖动作，不再重复 status 确认；对已受理的异步操作，先按已知典型时长做一次足够长的等待，再查一次终态，用退避替代多次短轮询。本例 8 次工具调用可缩至约 4 次且不丢决策信息。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:951:32cf139e857b48dc0ae4
evidence_refs: learning:learn:d8c216ddcd7f
created_at: 2026-09-18T14:35:36.290848+00:00
updated_at: 2026-09-18T14:35:36.290848+00:00
---
## Trigger
控制类命令（publish/deploy/restart dispatch）刚返回完整权威回执，且回执字段已覆盖下一步动作的全部前置条件；或异步动作已受理、该类操作典型耗时已知或可估计。

## Discriminator
逐字段对比：回执字段集合是否已包含下一步所需的全部字段（如 deployment_id + generation + git_head 均已在 publish 输出中出现，随后 status 只会返回同 schema 同字段的相同对象——重读不可能改变下一个决策）。对异步动作：受理记录的时间戳与该操作的典型耗时界定了状态有意义变化的最短间隔，短于该间隔的轮询不产生新信息。

## Short path
- 读 publish 回执本身：从未知量『deployment 是否已绑定 gen31』的答案字段（generation=31, git_head, deployment_id）直接推进，不重发 deployment status。
- 按既定顺序 dispatch 下一个依赖动作（feishu restart），把未知量收敛为该 action_id 的终态。
- 先执行一次间隔 ≥ 已知典型时长（本类重启约 10–30s）的等待，再单次查询该 action_id 终态；若仍 running，按几何退避延长间隔，而非固定短间隔反复查。
- 终态 succeeded 且 action_id/deployment_generation 与受理回执一致后，dispatch web restart，并按 requester-exit 协议立即结束本轮、不轮询。

## Stop conditions
- 回执已含下一步全部前置字段：直接推进，不再读状态。
- 异步动作到达与受理回执 action_id + generation 一致的终态（succeeded/failed）。
- 协议明确 dispatch 后不得轮询（等待请求方退出/锁释放）：立即收尾本轮。

## Verification
- 若仍执行了 status，逐字段比较其结果与回执：完全一致即证明该查询冗余（本例 deployment status 与 publish 输出逐字段相同）。
- 终态的 action_id 与 deployment_generation 必须与 dispatch 受理回执匹配，防止串读到其他动作。
- 确认回执与下一依赖动作之间没有可能使回执失效的状态变更（无其他写操作、无外部 drift）时，回执即真值。

## Counterexamples
- 回执缺少下一步需要的字段（如未返回 action_id 或 generation）：补一次 status 是必要的，不属冗余。
- 环境可能独立漂移（他人重新 publish、外部状态可变）：新鲜读数有真实价值，回执可能已过期，重查是防护而非冗余。
- 异步操作无耗时上界、历史上快速失败、或首轮查询已出现错误 detail：短间隔早查以便尽快捕获失败，单次长等待反而延迟发现。
- status 返回的 generation/git_head 与回执不一致：drift 已发生，此时这次查询恰恰是必要的。
