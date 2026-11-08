---
method_id: not-owned-denial-resolve-via-issuing-receipt-handle-never-respawn-2f32260a9263
name: not-owned-denial-resolve-via-issuing-receipt-handle-never-respawn
description: 对已确证存在且达标的托管资源（如 completed/PASS 的 review child）做 scoped 准入/状态调用被 DENIED 且 reason 为所有权类错误（review_child_not_owned）时，第一未知量不是『资格是否丢失、要不要重开』，而是『该权威把所有权绑定到哪个句柄』：所有权校验绑定的是签发回执（start 回执）里的会话句柄（如 cached:… 前缀 ID），不是叙事文本中的全局裸 ID（subagent_…）。下一跳=用签发句柄逐字重发同一 action；绝不据此 respawn/start 新实例。句柄重发仍 DENIED 才算所有权真丢失，停止上报 reason。
aliases: 准入查询说 child 不是我的怎么拿 PASS, not_owned 要不要重新 start, cached 句柄和裸 child id 用哪个, PASS 缓存跨 run 还能领吗, 别再开 reviewer 了怎么领缓存准入
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:2169:849ce5f71d97457e0641
evidence_refs: learning:learn:77d4e60beceb
created_at: 2026-11-08T11:43:31.781313+08:00
updated_at: 2026-11-08T11:43:31.781313+08:00
---
## Trigger
持有某资源已存在且达标的权威回执（child completed/PASS），对其 scoped 查询/准入调用返回所有权类拒绝（如 qualification=DENIED, reason=review_child_not_owned）；或指令原文/签发回执已明确写须用『精确 cached:… ID』这类带命名空间前缀的句柄做查询

## Discriminator
签发方回执中存在与裸资源 ID 不同的会话绑定句柄（前缀如 cached:…），且拒绝 reason 命名的维度是 ownership 而非『不存在/已过期/字段缺失』——这把『同参重发/换句柄/重开资源』三候选缩成『换签发句柄重发』一个

## Short path
- 发起 scoped 调用前，先在指令原文/签发回执里找『精确句柄』指定句并逐字作参数；叙事句里的裸 child ID 只当实体描述，不作调用参数
- 若已吃到 not_owned：改用签发回执的精确句柄重发同一 action（status），期间禁止任何新的 start/spawn
- 用成功回执的 reused_from_child_id 与 candidate_sha256 回显，确认句柄与裸 ID 指向同一实体、SHA 与已知值一致
- 准入在手后按既定边界执行被授权动作（本例：只重跑一次原版 ci_gate），有界 wait（单次不超过该工具上限）到 terminal
- 收口：账本记录已核事实；receipts/lane/checkpoint 写入遇 version_conflict 时取最新版本重试一次即可，按边界停止

## Stop conditions
- 以精确句柄取得 qualification=PASS 且 candidate SHA 与已知值一致
- 同一签发句柄重发后仍 DENIED（所有权真丢失）→ 停止并报告具体 reason，不再换措辞重试、不 respawn
- 被授权动作已由真实终态回执（exit=0）验证，按收敛边界停止，不进入未授权阶段

## Verification
- 成功回执的 reused_from_child_id 应等于叙事中的裸 child ID，candidate_sha256 与任务书已知值逐字一致
- 本次会话未产生新的 start/spawn 调用（无误增 reviewer）
- 拒绝 reason 的维度已归类为 ownership 而非 TTL/字段缺失，才允许走换句柄分支

## Counterexamples
- 签发回执只有裸 ID、无独立句柄：not_owned 表示跨 run 所有权真漂移，换参重发只会循环；正确动作是按协议重新 start（若收敛边界允许）或直接上报
- reason 是过期/撤销/缺失字段等非 ownership 维度：换句柄无效，应按 reason 命名的维度修复调用
- 查询通道本身不做所有权校验（任意 ID 可查）：不会出现 not_owned 分支，裸 ID 查询即终态
