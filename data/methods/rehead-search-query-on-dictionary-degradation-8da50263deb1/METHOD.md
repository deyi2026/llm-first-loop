---
method_id: rehead-search-query-on-dictionary-degradation-8da50263deb1
name: rehead-search-query-on-dictionary-degradation
description: web_search 结果集整体退化为对 query 首个常见词的词典/百科释义时，这是后端按首词做词义降级匹配的机械签名，与查询语言和其余关键词无关。此时不要在语义层连续改写措辞（换语言/加限定词/换序），而应重构 query 使其以最罕见的专名/缩写/模型名开头，并对每个新 query 预检首词。本集 8 次 query 中 5 次被降级（production/端/具/real/speculative），仅有的两次有效 query 均以罕见术语 VLA 开头；降级规则被总结出后仍在 query 8 复发，说明需要把'首词检查'程序化为发 query 前置步骤。
aliases: 搜出来全是词典释义, 把生僻词挪到最前面, web_search 首词降级, 同一需求改三次措辞没用
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:40eeca85-e561-4f26-9faf-efda5823cb4b:75:469167882b8b147403c8
evidence_refs: learning:learn:14132ef7124d
created_at: 2026-10-10T14:41:55.021212+08:00
updated_at: 2026-10-10T14:41:55.021212+08:00
---
## Trigger
使用 web_search 类工具做知识检索时：某次结果集几乎全部是词典/百科条目且命中词等于 query 首词；或同一信息需求已连续 2 次以上改写措辞检索仍失败。

## Discriminator
结果集构成在失败当时即可见：唯一成功的 query 以罕见术语（VLA）开头；失败 query 全部以常见词开头，且每条返回都是对该首词的词典释义（baike/dictionary/iciba/collins 类域名垄断）。同一 backend 对 VLA 开头的 query 返回主题结果，证明是 query 首词触发的降级而非服务故障——这条事实在第一次降级后就足以否定'换措辞再试'路线。

## Short path
- 结果返回后先做机械检查：词典/百科域名占比、命中词是否==query 首词；成立即判定为降级，停止语义层改写。
- 定位触发词（query 首个常见词），重构 query：以本需求中最罕见的专名/缩写/模型名开头（如 VLA/A2A/vLLM），通用限定词后置。
- 重查后复检结果集构成；主题相关即直接抓取原文进入作答。
- 若新结果集与某条先前 query 完全相同，复用已有结果，不发新 query、不视为新证据。

## Stop conditions
- 结果集主题相关且覆盖子问题：停止检索，转抓取/作答。
- 以罕见词开头重试一次仍降级：不再对该 backend 改写措辞，切换 backend 或在答案中如实标注该线无信源。
- 候选 query 首词为常见词且无更罕见的等价术语可前置：先解决首词问题，不发出该 query。

## Verification
- 降级检测可程序化：词典域名黑名单占比 + 命中词==首词，两条件同时成立判降级。
- 与同 session 已知好结果集对照，区分 query 依赖的降级与 backend 全局故障。
- 重构后结果集域名构成应切换为主题站点（arxiv/github/技术博客）；未切换则判定修复无效。

## Counterexamples
- 查询目标本身就是常见词（词源/翻译/词典学类问题）：词典结果即正确答案，不适用本方法。
- backend 正常支持自然语言长 query 且返回主题结果：判别依据是结果集构成而非 query 字符串，无需强行以罕见词开头。
- 罕见词开头的 query 返回零结果或垃圾：罕见词非万能，应补第二个限定术语或换源，而不是继续假设发生了降级。
