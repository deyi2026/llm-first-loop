---
method_id: exact-id-hydrate-from-backing-store-on-truncated-hit-ca65ffc3114e
name: exact-id-hydrate-from-backing-store-on-truncated-hit
description: 当记录/事件检索命中目标条目但正文被展示层截断、且条目带稳定唯一 ID 时，不要对同一检索面换 kind/limit 变体重查，也不要转向全库内容搜索；改为定位其文件态持久层（如 JSONL audit 存储），用精确 ID 一次 grep 取回全文与状态/授权字段。随后若按既往会话撰写的方案文档实施，把文档内嵌文件路径当待验证声明，先经文件名/模块名检索解析再读，路径不存在视为文档过期信号而非重试信号。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a997d0bf-003d-4335-ade1-4f3981aa79e1:0:1d3ecc236980f9fefec2
evidence_refs: learning:learn:85ed576f7aa0
created_at: 2026-10-17T08:21:09.190565+08:00
updated_at: 2026-10-17T08:21:09.190565+08:00
---
## Trigger
记录/事件流检索返回命中但内容被截断，条目带全局唯一稳定 ID（如 EVO-日期-8hex），且系统存在文件态持久存储；或：要按一份既往会话撰写的建议/方案文档实施代码变更。

## Discriminator
命中本身证明记录已持久化且可按 ID 定位；截断是展示层限制而非信息缺失——对同一检索面的参数变体重查（换 kind、event_stream 再读）最多返回同一截断行的回声，只有从持久层按精确 ID 取回才能补全未知量（全文、status、override、归属 session）。同理，方案文档中的路径是撰写时点的意图快照，不是当前树的真值。

## Short path
- 首次检索按 ID 命中且截断：记下 ID、时间戳、kind，不再对同一检索面换参数重查或读事件流回声层
- 一次定位持久层：按存储文件名检索（如 *suggestions*.jsonl）或用 ID 做带 --include 过滤的定向 grep；存在多副本（活跃 data/、data_ab/、.releases/ 归档）时取当前活跃存储
- 精确 ID grep 该存储：一次取回全文记录（status、human_exec_override、归属 session_id、完整方案骨架与影响范围）
- 实施前把文档内嵌的每个文件路径经文件名/模块名检索（grep import 引用、find 文件名）解析到当前真实路径，再发起 read；连续第二个文档路径失败说明在照抄过期文档
- 生命周期动作（登记完成/状态流转）前，查该动作工具的既有教训核对状态前置与归属边界，不满足则如实留给人工通道
- 全文记录与当前仓库态两个未知量都已齐备即停止发现，进入执行与验证

## Stop conditions
- 持久层全文已取回，且其 ID/时间戳与首次检索命中一致
- 方案文档引用的全部路径已解析或证伪，当前实现位置确定
- 状态/授权断言以取回的权威记录为准，不再查询派生回声层（事件流、二次检索）

## Verification
- 全文记录的 ID/ts 与首次检索命中的 ID/ts 严格一致
- status、override、归属会话等关键字段读自持久层原文而非截断预览或记忆
- 每个实际读取的文件路径来自当前树的检索结果，而非文档原文照抄
- 生命周期收尾动作（如登记完成）在调用前已核对当前状态与归属边界，被确定性拒绝的路径不重试

## Counterexamples
- 检索命中已含完整正文（无截断标记）→ 直接使用并停止，无需寻找持久层
- 记录存于远端/无文件系统访问的封闭 API → 精确 ID grep 不可用，只能用该 API 自带的按 ID 水合能力，参数探索可能是唯一手段
- ID 在超大语料中不唯一（短前缀碰撞）→ 需叠加 kind/时间戳过滤，单靠 grep 会引入假命中
- 方案文档描述的是待新建文件的绿地布局 → 路径不存在是设计而非过期，解析结果应解读为『需创建』而非『文档不可信』
- 目标内容本来就在当前 artifact 内完整存在 → 无 hydration 未知量，不适用本方法
