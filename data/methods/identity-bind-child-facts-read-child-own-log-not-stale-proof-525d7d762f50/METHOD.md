---
method_id: identity-bind-child-facts-read-child-own-log-not-stale-proof-525d7d762f50
name: identity-bind-child-facts-read-child-own-log-not-stale-proof
description: 多轮修订门禁流程中核验『本次』子代理特有事实（真实 provider/model、settlement、outcome）时，任何同主题证据先做身份绑定检查：event_stream 回执自标 scope=current_session=父会话即说明该面不含子代理事件；遗留 proof/summary 文件首字段 child_id 与本次回执不符即为上一轮产物。权威面是子代理自身主日志（数据目录/event_logs/<child_id>.jsonl，路径约定可由任一权威回执的 source 字段确认），首次读取先 dump 键路径/类型再取白名单字段，不触碰 payload 正文。绑定失败立即换面，不在同一错误面换参数重试。
aliases: 旧child的provider证明文件还能信吗, 怎么核本次reviewer真实模型, event_stream里查不到子代理provider事件, 子代理事件日志在哪个文件, proof文件是上一轮revision的怎么办, 确认审查child确实是glm-5.3
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:bad8cd4a-da76-4e5f-a8e3-893bf57ea9f0:0:12ca749c3d6e2115b1c6
evidence_refs: learning:learn:e17742ec7608
created_at: 2026-11-09T20:29:14.181477+08:00
updated_at: 2026-11-09T20:29:14.181477+08:00
---
## Trigger
多轮修订门禁流程（审查→测试→修复→复审）中需要核验本次子代理/子会话实例特有的事实（真实 provider/model、transport settlement、outcome），且同一命名空间存在上一轮遗留的同主题 proof/summary 文件，或事件流工具默认查询范围为当前父会话。

## Discriminator
当前回执已携带本次实例唯一标识（child_id）；候选证据源自带可即时否证的身份标注——event_stream 回执标 scope=current_session:<父会话ID>（结构性不可能含子代理 provider 事件），遗留 proof 文件内容首字段 child_id≠本次 child_id（上一轮 revision 产物）。

## Short path
- 从 review_admission/status 回执取本次 child_id，把『证据必须绑定此 ID』设为采信前提
- 从任一权威回执的 source 字段或 topology 查询确认子会话日志寻址约定，直接读 data/event_logs/<child_id>.jsonl 并过滤目标事件类型（如 provider.transport.settled），不经过父会话事件流
- 首次读该日志 schema 未知时，先打印事件键路径+类型，再仅提取白名单字段 provider_id/model_id/outcome/provider_observed_model，不读 payload/raw
- 值满足门禁要求后立即执行下一动作（如完整 R9），不再枚举其他证据源或对已证伪的面换参数重查

## Stop conditions
- 目标事件已在子代理自身日志中找到、身份字段与本次 child_id 一致、且值满足门禁要求
- topology/status 等权威面已直接给出绑定本次 child_id 的所需字段
- 证据源身份标注不匹配被确认后立即放弃该源，不再对同一源重试

## Verification
- 每份被采信证据的 child_id/session_id/scope 字段与本次回执逐字一致
- 全程未读取 payload 正文、密钥或 raw 业务内容
- 结论仅覆盖本次实例，不外推到其他 child 或上一轮记录

## Counterexamples
- 要核验的是父会话自身或全局事实（自身 run 统计、仓库级状态）→ current_session 事件流正是权威面，不应绕道子日志
- 单轮流程且无历史遗留文件 → 唯一现有证明可直接读，无需额外绑定步骤
- 所需事实不随实例变化（静态设计约定、路径规范文档）→ 旧文件不因『旧』而失效
- 子代理日志不可访问但 topology 元数据已含所需字段 → 采信 topology 即止，不再翻日志
