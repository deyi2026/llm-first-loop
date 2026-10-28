---
method_id: search-success-lexical-garbage-reroute-via-alt-engine-or-authority-fetch-1ee3f9d5a8f1
name: search-success-lexical-garbage-reroute-via-alt-engine-or-authority-fetch
description: 默认搜索后端对精确领域多词查询（政策名+税率+年份+文号）返回 success，但命中全是查询首 token 的词典/百科条目、门户或行情首页、缩写词义解析——这是分词/词法检索签名，改措辞、换语言都无效。最多做一次跨语言对照确认后，停止向该后端重发；用原查询换通道：web_fetch 备用引擎的 HTML 搜索端点（中文原句可直接复用），或直接抓已知权威域（主管机关）的政策页，再从返回的官方链接取数逐条溯源。与显式失败循环（错误码/反爬壳）不同：此处工具报成功，陷阱正是 success 掩盖了检索失效。
aliases: 搜出来全是词义解释不是政策文件, 搜索引擎把中文长句拆成单词查了, 搜索结果跑偏时直接抓税务官网, bing查不到中文政策换DuckDuckGo抓取, 查询没报错但零相关命中
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:7a55ef15-90c4-4fd3-b70f-68887bc24e18:0:3e02324a75bef33949ec
evidence_refs: learning:learn:bb5b6fdd8574
created_at: 2026-10-26T08:07:48.867773+08:00
updated_at: 2026-10-26T08:07:48.867773+08:00
---
## Trigger
领域精确多词查询（中文或英文，含专名、税率数字、政策文号、年份）提交默认搜索工具，回执 status=success，但命中是对查询个别词的词法匹配：单字/单词百科、词义解析、门户或行情首页，对查询中的专名与数字零命中

## Discriminator
看结果形状不看状态码：命中是否只覆盖查询的首词/单字而非整个查询主题。再做一次且仅一次诊断对照——同一主题换另一语言或简化措辞重发：若仍是词法化垃圾（本集英文 IRS 查询返回『US 是缩写』类释义），即证实是后端检索能力问题而非措辞问题，后续任何重写都是浪费

## Short path
- 首次命中呈词法化签名后，未知量改为『哪个检索通道能处理领域查询』，不再继续改写措辞轰炸原后端
- 一次跨语言/简化对照查询：签名不变→判定后端不适合此类查询，封存该通道
- 用原查询换通道：web_fetch 备用引擎的 HTML 搜索端点，query 原样保留（中文亦可）
- 已知权威域（税务/财政主管机关）时直接 web_fetch 其政策库/topic 页，两路可并行
- 从返回的官方 URL 读取条文与数字，每个进入结论的参数都能追到一次成功抓取的权威页即停

## Stop conditions
- 核心参数（税率、征收方向、持有期档位、政策文号与生效日）逐项有已抓取权威页正文支撑
- 备用通道同样不可用且无已知权威域：退回原后端用 site:/精确文号收窄，并在交付中如实标注未核验项

## Verification
- 逐条检查引用的文号/税率是否出现在某次 web_fetch 成功回执正文里，而非搜索摘要
- 新旧通道对同一查询的命中相关性对照，确认『通道问题而非查询问题』的归因成立

## Counterexamples
- 命中中已有若干相关文档、只是夹杂噪声：属正常排序问题，继续调 query 而非换通道
- 工具显式报错/反爬 JS 壳/固定错误码：属 identical-failure-loop 类方法管辖区，本卡的 success-垃圾签名不适用
- 冷门专名一次查空（多半是文号或拼写写错）：先修正措辞，单次 miss 不足以判定后端失效
- 无可直取的权威域、也无 fetch 得通的备用引擎时，只能留在原后端内收窄检索
