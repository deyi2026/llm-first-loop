---
method_id: skip-uniform-audit-array-tail-probe-truncated-snapshot-hydration-a39b6096337a
name: skip-uniform-audit-array-tail-probe-truncated-snapshot-hydration
description: 工具回执被截断、需按 range 分块水合同一 evidence ref 时，若首块显示顶层摘要键之后是长而条目 schema 一致的审计/历史数组（如旧代次 lag 列表），而用户问题点名的是若干当前状态字段：不要顺序读完数组主体。把用户点名清单当检索契约，利用水合回执自带 range 元数据（count=0 的探测即可给总长定界）先做稀疏/尾段探测，定位数组结束点与摘要区，只补读命中缺失字段邻近分块；点名字段全部取得权威值即停，未读数组只归类为历史噪声并保持 partial-coverage 纪律。
aliases: 快照被一堆旧代差记录占满要不要全读, 大回执只找几个点名字段怎么读省事, 从后往前翻工具长输出, 审计历史列表先跳过去, 截断回执先探结尾再补中间
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:84549805-ec25-424e-a2dc-f41110319615:0:556406aecd4e7251adc4
evidence_refs: learning:learn:dffcb9ccce00
created_at: 2026-10-24T07:19:48.339988+08:00
updated_at: 2026-10-24T07:19:48.339988+08:00
---
## Trigger
只读预检/状态查询类任务：权威工具单次调用返回被截断的大快照，需对同一 evidence ref 做范围水合；首块可见顶层摘要键（如 admission_barriers）之后是长而均匀的审计/历史数组（条目 schema 完全一致，如 {generation, lag_generations, target} 旧代差记录），而用户逐项点名的当前状态字段（desired 代次/git_head/各服务 live/锁/屏障）尚未在首块全部出现。

## Discriminator
两条当时已见的事实：①用户请求本身就是所需键的清单，均匀审计数组的每个条目与这些键无交集，多读一个条目对任务信息量≈0；②水合回执自带 range 元数据（start/count/complete/next_start），一个 count=0 的探测即可给 blob 总长定界，而状态/摘要字段通常排在数组结束之后的尾段，尾段锚定只需 2~3 次调用。

## Short path
- 按任务契约调用一次权威工具（如 status），只消费头块；已出现的顶层键（如 admission_barriers=[]）立即记录为答案
- 头块剩余内容若是均匀审计/历史数组，标记该区为待跳过区，不做顺序续读（读完 0-8000 仍全是数组即可停止续读）
- 用大 offset 稀疏探测定界：count=0 的最小 offset 即尾界上方；从尾界处向前读尾段，通常直接命中 desired/git_head/matches_desired_generation 等摘要字段
- 对照点名清单：缺哪个字段（如 per-service live pid、idle_state），只补读其所在邻近分块，按需推进，不顺序回填数组区
- 所有点名字段取得权威值即停；汇报时把审计数组明确归类为历史代差信号而非当前状态，未读区不当作'不存在'

## Stop conditions
- 用户点名的每个字段都已从同一 evidence ref（同一 blob_sha256）的分块中取得权威值
- 水合回执 complete=true 且剩余未读内容确认为与问题无关的均匀数组
- 发现工具本身支持字段/target 过滤且调用契约允许多次调用时，改为源头收窄并停止范围分块操作

## Verification
- 每个汇报值可指回具体 range（start/长度）且与同一 blob_sha256 一致
- 未读区段只被描述为'未读的历史审计数组'，未被当作不存在或无异常（保持 partial-coverage 纪律）
- 点名字段清单逐项对照无遗漏后才收口结论；历史数组中的旧 generation 不得被引用为当前不稳定证据

## Counterexamples
- 用户问的就是数组本身（如各 target 代差分布、最老 lag 是多少）→ 数组本体是目标区，必须读，禁止跳过
- 首块即 complete=true 的小快照 → 直接分析，无需任何探测
- 数组条目非均匀、可能夹带 per-target 当前状态（如数组元素内嵌 live 信息）→ 不能按零信息跳过
- 工具支持 include/target 等过滤参数且任务契约允许重调 → 在调用侧收窄优先于分块探测
- 任务契约限定只调用一次且截断发生在数组中段之前、点名字段全在首块 → 无需水合
