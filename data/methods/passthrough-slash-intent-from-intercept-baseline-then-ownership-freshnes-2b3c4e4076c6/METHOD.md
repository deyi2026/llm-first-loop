---
method_id: passthrough-slash-intent-from-intercept-baseline-then-ownership-freshnes-2b3c4e4076c6
name: passthrough-slash-intent-from-intercept-baseline-then-ownership-freshness-triage
description: 极简斜杠/宿主风格命令穿透到模型时（同会话前例命令曾被宿主静默消费），先用穿透行为判定其为用户意图而非待检索的内置语义，跳过命令语义 doc 搜索；开局盘点把 goals/children/收件箱/队列按归属（我 vs 他 session）×新鲜度（当前窗口 vs 历史终态/陈旧）分区，只有『归属=我』或『广播且时间戳最新』的条目进入行动候选集；呈报唯一候选并请求授权后停止，不再拉与当前未知量无关的地貌信息。本例 6 次调用中命令语义搜索（miss、结果未用）与无目的 memory 拉取均为 sufficiency 后动作，可省。
aliases: 新会话开局盘点, 斜杠命令没被宿主拦截怎么办, 收件箱一堆 pending 哪些和我有关, 开局要不要搜命令文档, 开局状态按归属和新鲜度过滤
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:9a21b8fd-48b7-47a5-89f5-4b9d739d7129:534:cff7b05e837598de2058
evidence_refs: learning:learn:106faeef0d38
created_at: 2026-11-16T00:30:08.112938+08:00
updated_at: 2026-11-16T00:30:08.112938+08:00
---
## Trigger
极简斜杠/宿主风格命令（如 /new）作为用户输入穿透到模型，且同会话此前已有同类命令被宿主静默消费的对照基线；或多会话共享工作区的新会话起点需要裁定『现在有没有我该做的』。

## Discriminator
两条当时已可见的事实：① 同通道前例命令是否被宿主静默拦截——被拦=内置语义，穿透到达模型=用户字面意图，语义判定就此完成，无需 doc 检索；② 协调回执里的 to_session/owner 字段与时间戳——定向他 session=非我责，历史终态与陈旧 blocking=过时，仅 to_session 为空（广播）且时间戳落在当前窗口的条目是行动候选。

## Short path
- 以穿透行为判定命令语义：前例被静默消费而本条到达模型 → 按字面意图（新会话）处理，跳过命令语义搜索
- get_goal / coordination_status：未知量=我名下有无活动实体；按 owner 分区，他人 goal 与他人 child 不进入我的行动集
- help_inbox：未知量=有无需要我处理的消息；按 to_session（定向他人=排除，广播=候选）× 时间新鲜度（陈旧 blocking=排除）过滤
- 汇报分区结论与唯一候选（新鲜广播项），涉授权的改动先问后动，随后停止；不再做与未知量无关的地貌拉取（无目的 memory/宽检索）

## Stop conditions
- 命令语义已由穿透基线判定，且全部 pending/队列项均完成归属或新鲜度裁决（非我 / 过时 / 唯一候选已呈报并转授权）
- 状态汇报中每一行都已有权威回执支撑，无剩余未裁决条目

## Verification
- 复查最终状态表：每行可回指一条具体工具回执，无推测项
- 行动候选数 = to_session 为空 ∧ 时间戳在当前窗口的收件箱条数，应与实际呈报数一致
- 确认未因 search miss 或陈旧 blocking 项触发额外动作

## Counterexamples
- 会话首条消息、无前例拦截基线：一次有界 help/doc 查询命令语义是必要的，不能跳过
- 工作区文档确有斜杠命令登记且检索命中：按登记语义走，穿透推断让位
- 收件箱存在定向给我且 need=block 的消息：归属优先于新鲜度，再旧也必须处理
- 命令带参数或复合意图（如附带恢复目标）：穿透只解决『是否内置』，参数语义另需绑定
- 存在要求开局做 memory/约定检查的活跃用户约定：memory 拉取是有目的调用，不属 sufficiency 后动作
