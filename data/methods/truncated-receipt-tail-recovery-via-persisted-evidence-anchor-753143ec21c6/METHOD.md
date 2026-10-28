---
method_id: truncated-receipt-tail-recovery-via-persisted-evidence-anchor-753143ec21c6
name: truncated-receipt-tail-recovery-via-persisted-evidence-anchor
description: 长 JSON 工具回执在展示层被切断、所需段落（如目标服务的 manifest/pid/started_at）在切断点之后时，不要重发同参数只读调用（大概率复现同一截断），也不要扩大到目录/事件流枚举：该回执本身已带 ref/source 完整持久化进证据库，截断只是显示层。用只在尾部才会出现的实体名+结构字段名作锚点检索副本取回缺失段；若命中片段落在已可见前缀，属零信息命中，换锚重查一次即可。
aliases: 回执被截断去证据库捞全文, status 输出切掉一段怎么补, 截断 JSON 的尾部去哪找, 工具输出太长被切掉后半段, 用尾部字段名当锚点搜证据
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:62423b4e-2e2c-44f3-82e5-45126a6bce95:63:290201950454d08cd933
evidence_refs: learning:learn:e0655bc47475
created_at: 2026-10-25T08:07:56.907074+08:00
updated_at: 2026-10-25T08:07:56.907074+08:00
---
## Trigger
工具回执（如 service_control status 这类大状态 JSON）中途截断，决策所需的目标段落未显示，且回执在证据库有持久化副本（可见 ref/source 标记）

## Discriminator
回执引用带 evidence ref 与同源 source/acquired_at，证明全文已持久化、缺失只发生在显示层；且锚定词若取自可见前缀，命中片段会落在已可见区域（零信息），有效锚必须取目标实体名与只在尾部出现的结构字段名（pid/manifest/started_at 等）

## Short path
- 判定截断性质：断在数组/对象中段且回执带 ref/source → 全文在证据库，未知量收敛为『取回切断点之后的段落』
- 用尾部锚点（目标服务名 + manifest/pid/started_at 等结构词）查 evidence；命中片段落在已可见前缀视为无效命中，换锚重查一次
- 用取回段与可见部分拼合后直接做决策；不重发同参数调用，不扩大到目录/事件流发现
- 若结论需要的是『此刻』状态而非该回执时点状态，另发一次权威窄查并分开标注时间

## Stop conditions
- 所需段落已从同源副本取回且与可见尾部无缝拼合，决策事实齐备
- 锚点检索确认证据库副本同样残缺或无法命中尾部锚点 → 改走支持字段过滤/窄参数的权威重查

## Verification
- 命中 ref/source/acquired_at 与被截断回执同源同时点
- 取回片段与可见部分 JSON 结构连续、时间戳/序号衔接合理

## Counterexamples
- 截断发生在存储层（证据副本本身只有前缀）→ 锚点检索必失败，应窄参数权威重查
- 需要的是分钟级之后的活性/并发等『当前』事实 → 持久化副本只证回执时点，必须新查
- 只读工具便宜且支持按 target/字段收窄输出 → 直接窄参数重查一次比构造证据锚点更短
