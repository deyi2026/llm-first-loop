---
method_id: misdiagnosis-reframe-for-contradicted-diagnosis-case-search-622bdccf4354
name: misdiagnosis-reframe-for-contradicted-diagnosis-case-search
description: 用户问『文献中是否存在诊断A之后却出现与A矛盾结局B的案例』（如≥11周无胎心后活产）时，不要用A、B字面词共现检索文献库：两词各自常见，共现查询只返回相邻主题噪音。先语义重定框：任何『诊断被结局推翻』的真实病例必然以误诊/诊断错误术语发表或被审计收录，改用字段化查询（TITLE/ABS: misdiagnosis、wrongly diagnosed、false positive + 规范病名）直达误诊文献与全国审计；再从现行诊断标准/阈值验证研究（特异度近100%的cutoff）确证事件在该参数下是否可能。两端收口后如实报告阴性结论并声明检索边界（库、语言、发表偏倚）。
aliases: 搜不到反例案例就换误诊关键词, 诊断被结局推翻的病例报告怎么查, 关键词共现检索全是相邻主题噪音, 有没有例外病例的文献检索策略, 阴性结果文献检索如何收口, 反例存在性文献查询
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:0538a365-f45f-43cd-9e26-bb8994ce4643:0:26f4748e05a95944ed03
evidence_refs: learning:learn:182e4a0c655f
created_at: 2026-10-31T21:28:16.904113+08:00
updated_at: 2026-10-31T21:28:16.904113+08:00
---
## Trigger
用户提出例外/反例存在性问题：文献中是否存在『某诊断或判读成立后却出现与之矛盾结局』的案例（某参数下判失败却成功、判无却出现）；或已开始按诊断词+结局词做字面共现的文献检索。

## Discriminator
首批共现检索回执即可判别：每条命中只共享个别关键词（结局词、case report、孕周数），没有一条描述『诊断被结局推翻』这一事件本身，说明字面共现空间不会收敛；且该类事件若存在，其发表与索引术语必是误诊/诊断错误/false positive一族——这是检索前即可用的领域词汇学事实，不依赖后来读到的答案。

## Short path
- 识别问题类型为『诊断被结局推翻』的例外存在性查询，未知量=是否存在已发表案例，而非发生率
- 把检索键重定框为错误/失败术语族（misdiagnosis、wrongly diagnosed、diagnostic error、false positive + 规范病名），在文献API用TITLE/TITLE_ABS字段化查询，预期直达审计/系统级误诊证据
- 并行取另一权威端：现行诊断标准与验证研究（指南cutoff、特异度数据），确证在所述参数下事件是否可能
- 若两端均为阴性或『仅误诊』，停止扩展检索，输出：无正例+机制解释+误诊文献枚举+检索边界声明（库/语言/发表偏倚告诫）

## Stop conditions
- 误诊/审计文献与现行诊断标准两端都已取得可引用的权威结论，能同时回答『有无案例』与『为何可能/不可能』
- 字段化误诊检索在权威库返回确定性0命中（回执明确无匹配而非超时）且标准端已闭合，即可停止

## Verification
- 逐条承重命中读标题+摘要，确认其描述的事件就是『原诊断被后续结局推翻』，而非仅共享关键词
- 诊断阈值/特异度结论取自现行指南或高被引验证研究并注明PMID/DOI
- 阴性结论附明确检索边界（数据库、语言、检索式），保留发表偏倚告诫

## Counterexamples
- 问的是常见共现关系（危险因素X与结局B的关联、某治疗与成功率）时，字面共现检索本身就是正解，套误诊框架反而漏检
- 领域错误术语并非misdiagnosis（筛查领域用false positive、检验领域用analytical error）时，需先读一篇综述/指南确定领域规范词再做字段化检索
- 用户问发生率/比例而非『有没有案例』时，应转队列或系统综述框架，误诊案例检索只能回答存在性
