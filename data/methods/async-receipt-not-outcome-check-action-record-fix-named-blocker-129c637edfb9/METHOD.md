---
method_id: async-receipt-not-outcome-check-action-record-fix-named-blocker-129c637edfb9
name: async-receipt-not-outcome-check-action-record-fix-named-blocker
description: 两阶段/异步控制动作的'受理'回执只代表登记，不等于执行。当预期效果未发生（或即将宣称生效之前），第一步用上一轮回执中的 action_id 查控制面的动作终态记录；若 failed，其 detail 会点名确切前置条件（如 tracked worktree dirty）。随后到该条件所属的权威源直接验证（dirty → git status --porcelain，区分 tracked/untracked），跳过进程层探测与源码宽搜；选择不改变绑定不变量（HEAD/generation）的最小可逆修复（如 git stash 单个 tracked 脏文件），从而无需 operator-only 的 republish；按原 expected_generation 重发后，做且仅做一次终态核查，用 waiting_*/空 detail 区分'真排队'与'登记即秒败'，然后立即结束本轮，效果级验证留待下轮。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16fe103b-bd92-4cdd-984a-f6cd5b45235c:280:1f906f680f71eff26de2
evidence_refs: learning:learn:f9d20936e03b
created_at: 2026-09-20T17:05:38.357881+00:00
updated_at: 2026-09-20T17:05:38.357881+00:00
---
## Trigger
两阶段/异步（先登记后执行）动作此前只拿到'受理'回执，随后用户或监控报告预期效果未发生；或即将向用户宣称该动作已生效/已排队之前。

## Discriminator
受理回执与'非效果'观察直接矛盾时，唯一裁决源是按 action_id 查询的动作终态记录（上轮回执已带 action_id，状态回执已展示控制面按动作记录状态的结构）；且失败记录的 detail 字符串点名确切前置条件（本例：code_root tracked worktree is dirty），可直接到该条件所属权威源验证，无需换到进程层或源码层。

## Short path
- 用上一轮受理回执中的 action_id 查该动作在控制面的终态记录；未知量：受理后究竟是 succeeded/failed/queued？
- 若 failed，把 detail 点名的前置条件当作唯一待验证事实；未知量：哪个确切条件未满足？
- 到该条件所属权威源直接核验（dirty → git status --porcelain，tracked 与 untracked 分列）；未知量：堵点是哪个文件、是否权限内可逆清除？
- 实施不改 HEAD/generation 的最小可逆修复（如 git stash 指定 tracked 文件）并复验 tracked 干净；未知量：能否避免触发 operator-only 的 republish？
- 按原 expected_generation 重发动作取得新 action_id；若回执声明两阶段等待，则不轮询。
- 做一次终态核查：status=waiting_* 且 detail 为空、updated_at 晚于 created_at → 真排队，交代下轮效果验证标准后立即结束本轮；status=failed → 回到第 2 步。

## Stop conditions
- 动作终态为 succeeded，或 waiting_* 且已明确下轮效果级验证标准（如 pid/started_at 变化、新配置在页面可见）
- 失败 detail 点名的条件已在其权威源确认修复，且重发动作的终态记录非 failed

## Verification
- 结论只引用动作记录的 status/detail 与条件所属权威源的原始输出（如 git status --porcelain），二者一致
- 宣称'已排队'必须有终态记录支撑（waiting_*、空 detail、updated_at 晚于 created_at），不得以受理回执替代
- 效果级验证（pid 变化/新配置生效）在下一轮完成前，不向用户宣称修复生效

## Counterexamples
- 同步工具的成功回执即最终结果（如读文件已返回内容）：不存在独立终态，追加查询是无信息动作
- 失败 detail 只是笼统的 internal error、不点名可独立验证的前置条件：此短路失效，需回到常规诊断/日志排查
- 修复必须产生新提交、HEAD 会变化：绑定不变量被打破，最小可逆修复（stash）不足，需走 operator publish 等更高权限流程
- 系统没有动作注册表或按 id 查询接口：无法取终态记录，只能直接观测效果本身
