---
method_id: schema-first-before-first-use-and-prefer-receipt-named-channel-2e2f5a531b58
name: schema-first-before-first-use-and-prefer-receipt-named-channel
description: 会话内首次调用某工具前，先读其完整 Schema/契约再选路线；把契约里的硬约束（URL 白名单、预绑定变量、安全门控）当作物理可达性事实——它们能整体否决一条取证路线，而非'偏好'。同时，若手头回执已把当前未知量的职责显式指给生态内另一工具（如 schema 文本写明 'wait 属于 browser_perceive'），优先沿这条被点名的通道做最小验证，而不是先试未读契约的外部工具。失败后才补读 schema 的顺序，会多付一次失败调用，还可能基于错误归因给出公开断言、之后再花成本纠错。本集该路线切换还附带产生了两次修正性陈述。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:9f3f9ab8-30d9-4a2d-9f58-148054503778:2090:665cb1bfa2c242b2aa9e
evidence_refs: learning:learn:c029e8e03134
created_at: 2026-10-11T00:15:12.198104+08:00
updated_at: 2026-10-11T00:15:12.198104+08:00
---
## Trigger
需要用尚未在本会话调用过的工具去获取证据，且该未知量存在多条候选路线（生态内已用工具 vs 外部/新工具），路线选择将决定后续动作序列。

## Discriminator
两个当时已可见的事实：(1) 该工具在本 episode 无成功调用记录、其 Schema 未读，而 get_tool_schema 恰在前一步刚被用过（先读后用的模式已在上下文示范）；(2) 已读回执明文把观察/谓词职责指给生态内工具（browser_operate 的 schema 写明 'wait 属于 browser_perceive，不在 actuation provider contract'），且 browser_perceive 回执已暴露 observed_value 可读。

## Short path
- 对未知量列出候选路线，先盘点各路线工具是否已读过契约
- 对未读契约的工具先 get_tool_schema；把白名单/预绑定/gating 当作可达性判据，直接淘汰不可达路线（本集：zhihu 不在 goto 白名单 → 外部路线零试错否决）
- 回执已点名的生态内通道可覆盖未知量时，沿它做最小谓词验证（eq 探测 + observed_value）
- 通道覆盖不到的部分（如码位级读取）如实标注未核验，不强行转去未读契约的新路线
- 拿到回执级证据即停，不追加同义确认

## Stop conditions
- 权威回执已给出所需事实（predicate 结果 + observed_value），进入成稿/提交
- Schema 显示路线物理不可达（目标域名不在白名单），立即弃用该路线
- 生态内通道明确不覆盖所需事实 → 记录为已核验的边界并转人工/审阅项，而不是无限换工具

## Verification
- 每个首次执行的工具，都能指出其 get_tool_schema 调用时间戳早于首次调用
- 最终证据链中每条关键结论的获取方式，与来源工具契约约束一致（未被白名单/门控否决），不存在'先失败后补读契约'的顺序倒置

## Counterexamples
- 工具已在本会话成功调用且契约仍在上下文内 → 再读 schema 属 post-sufficiency 动作，方法不适用
- 目标站点在白名单内且外部工具契约已知 → 直接按契约写脚本，不必绕回生态内通道
- 未知量确实需要外部工具独有能力且生态内通道不覆盖 → 方法不禁止外部路线，只要求契约先读；若契约根本不可得，改用一次最小 dry-run 探测契约，而非按猜测的 API 全量书写
