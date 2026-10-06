---
method_id: classify-unknowns-before-discovery-dont-rederive-in-hand-frame-4d24ca86764c
name: classify-unknowns-before-discovery-dont-rederive-in-hand-frame
description: 对'给分析/建议'类任务，先区分手头材料已回答的未知量（外部参照系）与必须新观测的未知量（本地方状态）。当待发动作的目标已被手头 artifact 覆盖——典型信号：搜索关键词全部取自该材料、回执显示该 URL 刚抓取过、或 miss 回执已列出通道覆盖与主题无关——该动作只能复述或引入噪音。预算应转向本地权威观测物（配置快照、源码适配器、注册统计）。确需核验低权威材料时，定向一手来源，而非泛关键词搜索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ba2daf39-ade3-4308-855e-bf3018c00381:4:0de9aceb6ac005d6ea81
evidence_refs: learning:learn:7e5ad560618d
created_at: 2026-10-06T06:25:19.276505+08:00
updated_at: 2026-10-06T06:25:19.276505+08:00
---
## Trigger
用户要求对当前系统/项目做能力/生态/差距分析并给出建议，且已抓取或持有一份外部参照材料（文章、规格、评测）

## Discriminator
发出 web_search/重复抓取/换词重搜前，当时已可见的判别事实：(a) bing 查询词（Claude Code Mods/插件生态/DeepSeek Harness/一切皆插件）全部来自已读文章，而该文 extract 已完整给出外部机制（Mods 定制、DSH 一切皆插件、兼容层实验性与子集论、Agent 创建入口）；(b) search_docs 首次未命中回执已列出 docs 最近主题全为 attestation/browser/argv 类，与生态主题无关；(c) 抓取回执显示同一静态 URL 于 133 秒前抓取过并建议复用。任一成立即说明目标未知量已被回答或先验极低。

## Short path
- 抓取参照文章一次（或直接复用 133 秒前的抓取回执），解决'外部玩家机制是什么'
- architecture_status 读配置快照，解决'LFL 当前启用哪些能力'（如 semantic_method_enabled=false、各 semantic 通道开关）
- search_files→read_file 定位既有互操作适配器源码（tools_skill_dsh.py），解决'已有什么生态管道与安全红线'
- skill_list/search_records 盘点技能与方法存量，解决'资产规模与漏斗状态'
- 用已覆盖参照系对比本地观测做差距映射并产出建议；不再发出任何指向已回答未知量的搜索

## Stop conditions
- 外部参照系已被手头材料覆盖且本地可观测状态（config/源码/注册表）采集完毕 → 停止发现，进入综合分析
- 每个动作发出前须指认它解决哪个尚未覆盖的未知量；指认不出就不发

## Verification
- 最终分析中对系统现状的每条事实断言可溯源到本地权威观测（config 键、源码行、注册统计），而非检索噪音
- 不存在关键词完全来自手头材料的外部搜索；若声明'已核实'，核验必须定向一手来源（官方文档/changelog/仓库）且结果在答案中被实际引用
- 统计无信息动作：复述型搜索、刚抓取材料的重抓、同通道换词重试应为 0

## Counterexamples
- 手头材料是聚合/转载类低权威源且任务要对外部事实下硬结论：需要核验，应定向一手来源（官方仓库/文档），既不能因'frame 已在手'跳过核验，也不能用泛关键词搜索冒充核验（本集 bing 返回的全是品牌主页噪音）
- 开放未知量本身在外部（如'除文中两家外还有哪些同类插件生态'）：手头材料只覆盖 frame 一部分，外部搜索正是正确动作
- 目标系统不可本地观测（非当前运行环境、无配置/源码/注册表访问）：本地 grounding 不可行，只能依赖给定材料或向用户求证
