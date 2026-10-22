---
method_id: prior-art-via-declared-sot-and-records-before-rule-authoring-a970cd148bfa
name: prior-art-via-declared-sot-and-records-before-rule-authoring
description: 在自声明为唯一真相源的治理/规则文件中新增条款前，'是否已有类似条款或先例方法'只从两个已验证来源回答：SoT 本身（相邻条款、编号空缺）与 records 有界检索（kind 限 method/experience，命中后一行裁决）。不做 repo 级文件名枚举——生成工件（eval 结果、浏览器 profile、备份）会淹没治理内容命中。新条款映射到既有记账/执行通道，不建平行账本。写后验证分两层：跑同步测试并枚举其断言确认覆盖语义；测试未覆盖的轴（如编号唯一性）用 grep 直接核验。
aliases: 加条款前先查有没有同款先例, 别按文件名在仓库里乱翻, 生成物会淹没治理条款, 不新开平行账本, single source of truth, 条款编号撞车了
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:775390eb-191e-4f71-9b0c-745ac8f072db:0:3b4cbc74133f8f596cb7
evidence_refs: learning:learn:121985059115
created_at: 2026-10-14T08:09:07.255393+08:00
updated_at: 2026-10-23T05:52:04.357625+08:00
---
## Trigger
需要向存在自声明'唯一真相源'的治理/规则文件新增或修改条款，且当前未知量是'是否已有类似条款/先例方法'时；尤其在仓库含大量生成工件（eval 输出、浏览器 profile、备份目录）使文件名搜索退化为噪声源的环境。

## Discriminator
两个在扩散发生前已可见的事实：(1) SoT 文件头部自声明为唯一规则真相源（含'不得进 universal prompt'等边界）；(2) records 检索已返回与本次诉求同机制的既有条目（如 hold 状态候选方法，其'开局检索·使用裁决·收尾结算'与用户要求几乎逐字对应）。任一成立即把'已有什么'窄化到 SoT+records 两源，repo 级文件名枚举对该未知量零增量。

## Short path
- 读 SoT 头部，确认唯一真相源声明与相关既有条款（本例 RULE-AI-18/22/29），未知量：既有约束与衔接点
- 有界 search_records（≤2 类、任务关键词）取先例候选，命中后一行裁决采用与否；零命中如实记后推进
- 补读 SoT 至完整，确定插入点、编号空缺（不复用历史空缺号）与相邻条款锚点
- 编辑：新条款映射既有通道（如 record_use），零程序改动、零平行账本
- 验证：同步测试通过后枚举其 def test_ 确认覆盖语义；未被覆盖的轴（编号唯一性、写后复读一致）用 grep/复读直接核验，然后停止

## Stop conditions
- SoT 与 records 已裁决'是否有先例'，编辑后测试通过且直接核验（唯一性/复读一致）完成
- records 零命中且 SoT 无相关条款：如实记'无先例'后直接撰写，不换词重检、不扫文件名

## Verification
- 写后复读一致；新条目在 SoT 内 grep 计数=1（编号唯一）
- 同步测试通过，且已枚举测试断言确认其确实覆盖（或显式不覆盖后补做）本次改动轴，避免'绿色但不覆盖'假验证
- 条款引用的既有机制/通道（记账、生命周期工具）在 SoT 或代码中真实存在

## Counterexamples
- 问题对象是代码实现行为（哪个文件实现了某机制）→ 应走工作区内容搜索/读实现，SoT 与 records 不含此答案
- SoT 自声明已过期、规则实际散落多处 → 先核治理索引或同步测试确认真实存放地再动手
- 目标本身就是定位某类文件且仓库无生成工件污染 → 文件名搜索即正确通道，无需绕行 records
