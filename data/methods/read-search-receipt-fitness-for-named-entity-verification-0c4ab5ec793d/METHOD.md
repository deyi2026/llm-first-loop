---
method_id: read-search-receipt-fitness-for-named-entity-verification-0c4ab5ec793d
name: read-search-receipt-fitness-for-named-entity-verification
description: 用网页搜索核验具名实体（基准/库/产品）是否具备某属性时，把回执本身当作查询适配度的证据来读：偏题泛化命中（裸年份→日历页、专名撞形→同形泛词页）说明独特 token 被稀释，应改为引号精确短语+权威域限定，而不是加更多词；改写后回执与先前逐条相同说明该实体在此后端已检索穷尽，应标记未证实并停止换词重查；回执已列出多个官方源时优先抓 canonical repo/静态页而非 JS 营销主站，失败则降级到官方域摘要+repo 并披露证据层级。本集 6 次调用中 3 次浪费于这三种可从回执直接判读的形态。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b08a5a88-4c62-47f9-84ed-c3cb191c061d:62:28ba7f3ed7944dc3d638
evidence_refs: learning:learn:e3a07932529f
created_at: 2026-10-14T19:52:14.963068+08:00
updated_at: 2026-10-14T19:52:14.963068+08:00
---
## Trigger
通过网页搜索核验具名实体（基准/库/产品/版本）的存在性或属性（滚动更新、防污染、新版本、发布时间），且查询中含裸年份、版本号、或可与泛化名词撞形的专名时

## Discriminator
回执内容本身即可判读：(1) 命中页与查询只共享泛化 token（'2026'→日历页、'Terminal'→Windows Terminal 教程页）= 专名被稀释；(2) 改写后的查询返回与上一查询逐条相同的 URL 集合 = 该实体/角度在此后端已穷尽；(3) 回执已同时列出主站、github.io、github repo 多个官方源 = 存在更可抓取的静态替代，无需先攻 JS 主站

## Short path
- 把未知量表述为「具名实体 × 属性」，先用属性词汇查一次（如 contamination-free / releases new questions），一条查询覆盖一类候选，本集第 2 条查询即此形态并直接命中
- 对每个具名候选只发一条查询：全名加引号并限定权威域（site:github.com 或 arxiv），不以裸年份或泛化名词开头
- 逐条读取回执的适配度：偏题泛化命中→改成引号精确短语（不追加更多词）；与先前查询结果完全相同→标记该实体未证实并停止换词重查
- 需要抓全文时，从回执列出的官方源中优先选 canonical repo/静态官方页；主站 JS 壳抓取失败则降级到官方域摘要+repo，并在答案中披露证据层级
- 以「已证实/未证实」分层作答：每个具名候选要么有官方域或 canonical repo 的回执支撑，要么显式标注未证实，而非静默丢弃或照抄

## Stop conditions
- 各具名候选已从官方域摘要或 canonical repo 取得属性级证据
- 同一查询形态连续两次失败（劫持偏题或重复回执）→该实体记为未证实并披露，不再第三次换词
- 官方主站不可抓取且静态替代源已给出可核验事实

## Verification
- 最终答案中每条事实可追溯到一条具体回执 URL（官方域或 canonical repo）
- 被丢弃或降级的候选在答案中显式标注「未证实/未能确认存在」
- 跨查询比对 URL 集合：出现完全相同结果集后不再发起同意图查询

## Counterexamples
- 真正开放式发现（用户要『任何新东西』、无具名锚点）时宽泛查询合法，不应机械套用引号精确查询——但仍避免裸年份开头
- 语义检索后端能正确处理未加引号专名时，引号与域限定非必需；判据始终是回执内容而非机械规则
- 重复回执由 CDN/缓存造成且新查询意图实质不同（换了未知量）时，不构成穷尽信号
- 摘要来源是 SEO 镜像或过时拷贝时，官方域摘要级证据不足，必须抵达 canonical 源后才能下结论
