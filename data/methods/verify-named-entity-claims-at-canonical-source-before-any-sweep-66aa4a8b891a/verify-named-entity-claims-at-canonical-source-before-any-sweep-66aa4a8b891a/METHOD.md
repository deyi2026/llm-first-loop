---
method_id: verify-named-entity-claims-at-canonical-source-before-any-sweep-66aa4a8b891a
name: verify-named-entity-claims-at-canonical-source-before-any-sweep
description: 读文章/二手资料类任务在首次抓取已拿到全文后，若要对其中指向具名外部项目的断言做核验，第一动作是按文中已给出的精确标识（org/repo、包名、官网）直接抓取该项目的 canonical artifact（README/官方文档），一次调用完成比对；不要先对本地工作区做多轮全库扫描（外部项目与本地无因果边，短 token 文件名子串搜索还会被无关词根吞掉、易超时），也不要先发泛关键词搜索引擎查询（小众开发项目常返回高 SEO 无关站点）。canonical 来源不可达或断言无标识时才升级到搜索/镜像/归档，并显式标注证据等级。核验的理想成本约 1 次 canonical 抓取。
aliases: 文章里的项目说法去哪核实, 二手文章断言交叉核对上游, 本地乱搜外部项目全无结果, 搜索引擎搜出来全是无关站点, 抓完文章要查证上游说法, 按文中仓库名直接拉 README 核对
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:a7ee8d09-05f3-46ec-9b83-9d4075332c6a:0:0a1587444502e83060e7
evidence_refs: learning:learn:99b38f3f26f2
created_at: 2026-11-19T00:19:06.868560+08:00
updated_at: 2026-11-19T00:19:06.868560+08:00
---
## Trigger
已完整抓取一篇文章/二手资料并要做要点整理或事实核验，其中待核断言指向一个具名外部项目/来源，且文中已给出可定位的精确标识（org/repo、包名、官网域名）。

## Discriminator
进入核验时文章全文已在手：断言主体被点名、canonical 来源可一步构造 URL 直取；同时任务材料中没有任何指向本地工作区文件的线索（用户只给了链接，本地仓库与该外部项目无因果边）。此时权威面是上游本体，不是本地副本，也不是搜索引擎关键词结果。

## Short path
- 确认文章全文已到手、digest 未知量已解决；列出真正需要外部核验的具体断言（如"已被 X 采用"）
- 在文中定位该断言主体的精确上游标识，直接构造并抓取 canonical artifact（org/repo 的 README/官方文档页），一次调用
- 只针对该断言比对 canonical 来源的对应段落/清单，分一致、不一致、未覆盖三档记录
- canonical 来源不可达（404/私有/超时）才升级：换镜像/归档或做一次定向搜索，并带证据降级标注
- 仅当任务本身涉及本地材料时才做本地检索：用精确标识定点搜一次；短 token 的文件名子串搜索会被 board 之类词根吞掉，出现超时或全无关命中即停，不换参数重扫
- 输出整理结果并停止

## Stop conditions
- 已从被点名的 canonical 来源取得与断言直接对应的原文（一致或不一致均可定性）
- 断言主体在文中无任何可定位上游标识，且一次定向搜索/归档尝试也未命中——记录证据等级后收尾

## Verification
- 核验结论必须引用 canonical 来源的具体段落/清单条目，而非搜索结果摘要或本地文件名命中
- canonical 来源未覆盖的断言在答案中显式标注证据等级（仅文章来源 / 已核上游 / 本地未验证）
- 复盘工具账：核验阶段理想成本约等于 1 次 canonical 抓取；出现本地多轮全库扫描、同参重复搜索或泛关键词 web 查询在前，即偏离本方法

## Counterexamples
- 文章未给出任何 repo/官网/包名等可定位标识——canonical 直取不可行，此时搜索/归档发现才是正路
- 断言对象是本地工作区自身状态（"本仓库是否已含 X"）——权威面是本地，用精确标识定点搜一次即可，不该去拉外部 README
- 任务是整仓/子树引入（要拿整棵树落地）——适用 clone-first 类方法，读 README 核对不解决问题
- 用户只要求摘要文章、未要求核真——直接整理文章内容即可，整个核验阶段省略
