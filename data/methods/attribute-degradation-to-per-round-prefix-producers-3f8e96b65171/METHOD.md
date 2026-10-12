---
method_id: attribute-degradation-to-per-round-prefix-producers-3f8e96b65171
name: attribute-degradation-to-per-round-prefix-producers
description: 当聚合指标（如缓存命中率）下降、且首个状态快照已否证用户提名的斯部原因时，把同一快照中的组合统计直接用作下一步查询的判别器：若某前缀分段（history）明显被逐轮重建/压缩，应把事件流查询指向近窗口的逐轮前缀构建事件，而不是重验已否证的原因、拉旧告警窗口或先翻量化 blob。归因必须落到具体逐轮生产者并各带事件证据；无证据子问题保持明确不可判定。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:173:2fbe786416c0707a3c67
evidence_refs: learning:learn:1cb39c722feb
created_at: 2026-09-20T08:58:39.918333+00:00
updated_at: 2026-09-20T08:58:39.918333+00:00
---
## Trigger
聚合指标（缓存命中率/前缀复用）持续下降，用户提名的解释（如模型切换）已被用户自己否定但需验证，剩余候选原因有多个（切换/重启/TTL/LRU挤兑/运行时逐轮改写前缀）。

## Discriminator
首个状态快照已同时含两个事实：model_fallback.active=false（切换假设已死）与可见 history 仅 1,048 字符/1.3%（246 轮、168K 条已归档）——即上下文尾部每轮被重建。该事实在第一次 event_stream 之前就已把'为何掉缓存'从{切换,重启,TTL,挤兑,改写}收窄到改写侧；当时应直接把事件流查询指向近窗口的 build_messages/tool_working_set/recent_continuity 事件，而不是先拉旧的切换告警窗口（9 条过期告警，与用户报告一致但无新信息），事后再对同一 source class 换 scope 重查。

## Short path
- 拉一次运行时状态快照；未知量：用户提名的切换是否仍在发生。一次调用同时否证切换（fallback inactive）并暴露组合证据：history 1.3%/246 轮 → 前缀尾部每轮重写。
- 事件流直接查近窗口的前缀构建事件；未知量：哪一级管线每轮改变前缀字节。得到逐轮变化值：预算逐轮收缩、raw_tool_chars 17,340→24,242→36,063、rehydrated=true 且模式翻转。
- ps 查服务进程 uptime；未知量：推理后端是否重启（重启单独即可清零缓存）。结果 5 天+ 无重启，排除。
- 对比全局桶与单 session 命中率；未知量：provider/全局原因还是 session 局部。其他 session 97.7%、flash 桶 75.6% 健康 → session 局部改写。
- 归因完成：三个改写源各带逐轮事件证据，给出字节级稳定性修复建议；无证据子问题（本轮头部 0% 是 TTL 还是头部字节变化）明确标注不可判定，停止。

## Stop conditions
- 每个逐轮前缀分段都有具名改写源，且各带至少一条具体事件证据
- 出现更新的外部原因证据（新鲜切换告警、进程重启、全局桶命中率同步崩塌）→ 外部原因胜出，改写分解分析暂停

## Verification
- 改写源事件中的数值逐轮变化（raw_tool_chars 17,340→24,242→36,063；rehydrated=true；预算 1,000,000→560,146），而模型标签/进程 uptime/全局桶命中率保持稳定
- 命中模式与归因自洽：最新请求 cached 0/25,337（仅头部可命中）而同 key 其他 session 97.7% —— 若是全局/挤兑原因则对面不可能稳住

## Counterexamples
- 事件流显示新鲜切换告警或进程 uptime 只有几分钟：重启/切换已完整解释 0% 命中，先修外部原因，不做前缀生产者分解
- 日志中不存在逐轮前缀重建事件（无 build_messages/tool_working_set/recent_continuity 类事件）：没有改写证据，不得强行归因为运行时改写
- provider 侧缓存指标缺失时，round-1 头部 0% 在 TTL 过期与头部字节变化之间必须保持不可判定（本 episode 正确地未定性），不可为了答案完整而硬归因
