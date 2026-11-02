---
method_id: identical-search-receipts-pivot-to-first-party-release-surface-73acbb12bca9
name: identical-search-receipts-pivot-to-first-party-release-surface
description: 调研某厂商新发布/传闻中的产品时，若通用 web 搜索回执只含厂商通用属性页（官网、GitHub org、HF org）而产品专名零命中，且换措辞重搜返回几乎相同的结果集——这本身就是『索引未收录该专名』的机械信号。此时停止继续改写查询词，直接枚举厂商一手发布面：org 的 repos API（sort=pushed）、官方 news/changelog 页。工程制品几乎总是先落到厂商自己的仓库/官网再被新闻索引收录，通常一步即命中制品；随后对一手文本做关键词计数来检验用户的动机性假设，一手面取尽后才转二手渠道并降级标注。本集 5 次近重复搜索（含漂移到无关同名实体与词典释义）后，一次 org repos API 调用即定位到目标制品仓。
aliases: 搜索结果一直重复还要换关键词吗, 查不到新品发布直接翻厂商GitHub, 新闻搜不到产品名走官方渠道, 几次搜索返回同样的结果怎么破, 调研刚发布的产品先看官方仓库
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:09ebae20-dbcb-4a1d-96ca-cea2aa8541b5:1:945671172ae8a2264558
evidence_refs: learning:learn:a75aff31ec89
created_at: 2026-11-02T10:51:12.055607+08:00
updated_at: 2026-11-02T10:51:12.055607+08:00
---
## Trigger
调研厂商新发布或传闻产品：首次搜索回执只返回厂商通用属性页（官网/org/模型站）而无该产品专名的任何命中，或两次不同措辞的搜索返回几乎相同的 top 结果集

## Discriminator
回执里已经出现厂商权威一手渠道的 URL（GitHub org、官方 news、HF org），且回复集对措辞变化不敏感（相同结果）——说明继续改写查询词不会产生新信息，而厂商自己的发布枚举面尚未被查询

## Short path
- 首次搜索后检查回执：有产品专名命中吗？若无但已列出厂商 org/官网 URL，把下一未知量定为『厂商自己的发布面上是否存在该制品』
- 直接枚举一手发布面：org repos API（sort=pushed, per_page=40）与官方 news/changelog 页，按名称模糊匹配产品名与发布时间窗
- 命中疑似制品后读其 README/SETUP/docs，把用户动机性假设（如『为某方向做准备』）翻译成对一手文本的关键词计数与逐条核对
- 一手面取尽仍缺的输入（公众号原文、第三方评测）才转二手渠道，并显式标注证据等级
- 每次想换查询措辞前先确认：上一回执里可用的关键事实是否已被用尽

## Stop conditions
- 已从厂商一手渠道确认产品存在性、定位与机制描述，并完成与用户假设的对照检验
- 一手渠道完整枚举后确认无该制品 → 得出『传闻未获一手证实』或转二手来源，不再回通用搜索换词

## Verification
- 疑似制品的 owner、描述、更新时间与产品名及发布时间窗一致
- 报告中的关键断言均可指向一手文本；二手转述（媒体、论坛）显式降级标注，不冒充一手事实

## Counterexamples
- 产品是纯消费品/服务、无代码发布：org 枚举必然落空，应以官方 newsroom、应用商店、官方社媒为一手面
- 首次搜索已返回产品专属新闻/评测：直接读命中结果即可，无需切换渠道
- 结果中的『厂商』页面是同名无关组织（本集曾漂移到 deepin 操作系统词条）：先验证 org 身份再信任其枚举结果
- 任务需要市场反应或第三方基准：一手面只覆盖官方说法，证据面必须另行扩展而非以官方文档代替
