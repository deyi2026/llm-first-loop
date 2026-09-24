---
method_id: preflight-pin-freshness-before-cas-gated-restart-orders-e4f59f756260
name: preflight-pin-freshness-before-cas-gated-restart-orders
description: 在下达绑定 generation/git_head 的重启/部署单（执行器做 CAS binding 校验）之前，先做 pin 新鲜度预检：把 publish 回执中钉死的 desired git_head 与当前仓库 HEAD 对比，确认 publish 之后没有新 commit。pin 过期则绑定该代的每一单都必然 binding failed——应先 publish 新代绑定当前 HEAD，再对状态快照中所有 lagging 目标一次性补齐订单，最后逐 action_id 核对终态（受理≠完成），直至全部 succeeded 且身份一致。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:2324:12529a5e00d806fdbfc3
evidence_refs: learning:learn:53676e4522e4
created_at: 2026-09-24T04:40:27.356297+00:00
updated_at: 2026-09-24T04:40:27.356297+00:00
---
## Trigger
需要补发/追赶绑定既有 desired generation（expected_generation=N）的重启或部署单，且执行器会做 desired-head==实际HEAD 的 CAS 校验；典型情境是用户报告部分（但非全部）服务未滚动到目标代，且 publish 之后可能又有提交落下。

## Discriminator
publish 回执显式记录了该代钉死的 git_head，而当前 HEAD 一查即知：publish 之后若有任何 commit（哪怕是 skill/文档提交）落盘，则 pinned head ≠ 当前 HEAD，绑定该代的所有订单会被拒绝。这一事实在下达订单之前就可机械比对得出，不需要等失败回执里的 desired=X actual=Y 才知道。

## Short path
- 1. 从服务状态快照列出所有 lagging 目标（未知量：漏单范围是哪几个 target），不要只补其中一个。
- 2. 下单前预检 pin：比对 publish 回执的 git_head 与当前 HEAD（git log 看 publish 之后有无提交）；未知量：desired 绑定是否仍新鲜。
- 3. 若有提交落在 publish 之后 → 先 publish 新代绑定当前 HEAD，再下单；pin 新鲜则直接下单。
- 4. 对每一个 lagging 目标在同一代一次性受理重启单（批量完整，避免二次追赶）。
- 5. 等待后逐 action_id 查询终态；核对输出身份字段（generation、git_head、verify）与 publish 的绑定一致。
- 6. 全部目标 terminal=succeeded 且身份一致即停；failed 终态显式闭合。

## Stop conditions
- 所有 lagging 目标均查询到 terminal status=succeeded，且输出的 generation 与 git_head 与已 publish 代的绑定完全一致。
- 不存在已受理但未核对终态的 action_id（受理回执不算完成）。

## Verification
- 对每个 action_id 用 service_control(action=status) 或 event_stream(service_action_terminal) 查终态，不得把 accepted 当 succeeded。
- 核对成功输出中的身份三件套：generation、git_head、verify=confirmed_ok，与 publish 回执一致。
- 对照最初状态快照，确认补单覆盖了全部 lagging 目标而非子集。

## Counterexamples
- 执行器不做 git_head/CAS 绑定校验的重启系统：预检无意义，直接下单后核对终态即可。
- publish 之后确实无任何提交：pin 新鲜，跳过重发布立即下单，多余预检反添一步。
- 刻意回滚到旧版本的订单：desired≠HEAD 正是意图而非缺陷，不应触发重发布。
- 单目标部署无批量追赶问题：只有终态核对那一半方法适用。
