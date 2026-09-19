---
method_id: resolve-exact-keys-and-gate-fields-from-canonical-records-first-41b2cc442904
name: resolve-exact-keys-and-gate-fields-from-canonical-records-first
description: 本 episode 两处绕远同型：为取已知方法的精确 stable ref，先用描述性长句做语义搜索、miss 后再换更泛的词重试，才回落到列 store 目录直接取 key；对带准入门槛的生命周期流转（qualify/activate），只凭截断的 qualification 预览就发起调用，被拒后才补读全文确认 promotion=not_evaluated。方法：先定性未知量——是精确键/门槛字段，还是开放发现；前者直接读规范载体（列目录取精确 key、完整读取 record 全文逐字段对照门槛），字段缺失或 provenance 同源则不发起调用、记录合法补齐路径；被门槛拒绝时把错误命名的 precondition 当权威规格，补真实输入或放弃，绝不伪造字段绕过。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:111:b4f454b4a8998beca933
evidence_refs: learning:learn:fad5f7d7706a
created_at: 2026-09-17T14:57:53.125304+00:00
updated_at: 2026-09-17T14:57:53.125304+00:00
---
## Trigger
需要为已知名称的持久化记录（method/experience 等）解析精确 ID，或准备调用带准入门槛的状态变更/写入工具（生命周期流转、verified 写入），且记录本体或 store 清单在本地一步可读

## Discriminator
本次未知量是精确键或门槛字段而非开放发现（如自述目标即'取精确 stable ref'）；模糊搜索已诚实返回'未找到'（非错误，提供零 narrowing 信息）；门槛所需字段（如 promotion、evidence）存于本地 record 文件，一次全量读取即可核验，截断的 head 预览不构成审计依据

## Short path
- 先定性未知量：精确 ID / 门槛字段 / 开放发现，三者对应不同工具
- 精确 ID → 列 store 规范清单（目录 ls）直接取 key；不用描述性长句语义搜索，更不在 miss 后换更泛的词重试
- 门槛字段 → 完整读取对应 record 文件（非截断预览），逐字段对照门槛要求（字段值非空、provenance 非同源自证）
- 字段齐全且非自证 → 执行状态变更；字段缺失或同源 → 不发起调用，写下未来合法满足路径（如'需独立 run 记录 promotion=pass 后方可 activate'）
- 若已被门槛拒绝 → 按错误命名的 precondition 补真实输入重试（如附 evidence）；无真实证据则如实降级状态，不伪造、不放宽字段

## Stop conditions
- 精确 key 已从规范载体取得，且 record 全文的门槛字段已完整亲眼核验
- 或已判定门槛当前不可合法满足，且已记录补齐路径与下次复查点

## Verification
- exact-key 水合/读取命中，且内容与磁盘 record 全文一致
- 每次 gated 调用发起前，record 全文中每个门槛字段值均已完整读取确认（无截断段遗漏）
- 所有写入门槛拒绝均以真实输入解决，全程无伪造或放宽字段通过门槛的案例

## Counterexamples
- 开放发现场景（尚不知道目标记录是哪条）：语义搜索是正确首步，规范清单反而不定向；此时查询词应对准记录卡面词汇
- 门槛契约完全未知且无文档、调用安全可重放时：一次试探调用读回精确错误信息可能比先全量翻读或逆向源码更快——试探即发现
- 记录仅存在于远程 API、无本地清单或文件可读时：只能靠搜索与接口分页解析，本方法不适用
