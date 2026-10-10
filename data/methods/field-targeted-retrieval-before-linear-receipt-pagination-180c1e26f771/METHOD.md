---
method_id: field-targeted-retrieval-before-linear-receipt-pagination-180c1e26f771
name: field-targeted-retrieval-before-linear-receipt-pagination
description: 只读回执/evidence blob 被截断（complete=false、尾长未知）且截断点是体积庞大的批量历史数据（如长审计数组）时，若所需字段与该数组结构不同、且字段名可枚举（此前回执已展示同类字段），应直接用字段名/关键词定向检索定位目标记录，而不是按 next_start 线性翻页消费整个 blob。连续翻页确认仍是同质历史噪声后必须立即切换检索，不允许『再看几页』。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:007a1251-ae2c-4786-9ada-61948115af41:362:f83787c4755bfaef85af
evidence_refs: learning:learn:7faed4e49d7d
created_at: 2026-10-10T00:09:04.536356+08:00
updated_at: 2026-10-10T00:09:04.536356+08:00
---
## Trigger
需要某个截断回执中的特定记录（如某服务的运行时字段），但回执在一段与目标无关的批量历史数据中间被截断，且目标字段名此前已在同回执/同类回执中出现过、可枚举。

## Discriminator
进入摩擦点时已可见的两条事实：(1) 同一回执头部已含与目标同类的结构化运行时字段（pid、matches_desired_generation、restart_required），证明目标记录每服务一条、字段名唯一可检索；(2) 截断点位于历史审计数组内部，可见条目全是远低于当前代的旧数据且 complete=false、数组无可见终点。两条同时成立时，线性翻页的期望页数未知，定向检索一跳可达。

## Short path
- 首次只读回执截断时，先判断截断点是否就是目标记录所在结构（未知量：目标服务的运行时字段在哪里）
- 确认截断点是批量历史噪声且目标字段名可枚举 → 直接用字段名+目标服务名做定向检索，不调用 next_start 翻页（未知量：目标服务是否需要重启）
- 命中多条 ref 时按 acquired_at 取最新一条核对字段值
- 据检索结果签发动作；参数被契约拒绝时按错误回执一次性修正全部字段（必要时先读一次 schema），不逐字段试错
- 注册终态核验后停止

## Stop conditions
- 已从 acquired_at 最新的命中记录中取得目标服务的 pid/匹配代/是否需重启等关键字段
- 目标动作已受理（回执含 action_id/generation）且终态核验已排程

## Verification
- 命中记录的 source/producer 是同一权威控制面，且 acquired_at 为可获得的最新观测（多条命中时比较时间戳，不拿旧快照下结论）
- 动作回执字段与工具 schema 语义一致（如 restart 用 target，而非另一动作的可选参数名）

## Counterexamples
- 目标内容正是该批量数组的全量或统计（如需汇总全部滞后条目）→ 定向检索拿不到，分页/聚合读取才是正确路径
- 环境无检索工具或检索不支持按目标字段匹配 → 只能顺序读取
- blob 很小、预期 1–2 页即 complete=true → 直接顺序读完比检索更省，不套用本方法
