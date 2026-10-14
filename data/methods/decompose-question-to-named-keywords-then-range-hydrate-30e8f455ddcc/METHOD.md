---
method_id: decompose-question-to-named-keywords-then-range-hydrate-30e8f455ddcc
name: decompose-question-to-named-keywords-then-range-hydrate
description: 面对单次抓取会截断的长文档和具体分析性问题（如'是否属于拟合'）时，先把问题分解为2-4个'具名未知量'（动权重的算子/监督信号构造/泛化证据），用首屏或摘要中已出现的确切术语对已抓取语料做定向检索，只对命中区间做范围补读，而不是从头顺序分页翻完整篇。本集先翻完参考文献与附录、之后才检索定位主文方法段，多花约3-4次低价值分页抓取。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9ea7473b-ae27-4878-81af-8723306cccdf:8:3c4c544d97e2dfdf30f3
evidence_refs: learning:learn:74c5d3babd6c
created_at: 2026-10-14T14:20:10.698636+08:00
updated_at: 2026-10-14T14:20:10.698636+08:00
---
## Trigger
需要通读一个单次抓取会被截断的长文档（数万至十余万字符）来回答一个具体分析性问题（如'是否属于X''机制是否Y'），且已抓取的摘要/首屏已明确出现与问题相关的机制名、算子名或基准名。

## Discriminator
用户问题可分解为2-4个具名未知量，且首屏/摘要文本中已出现可精确检索的确切术语（如'supervised fine-tuning on self-generated trajectories'、基准名），这些术语即检索关键词；同时分页回执显示当前段落落在参考文献/附录等低相关区域，说明顺序分页未在缩小任何具名未知量。

## Short path
- 抓取首屏/摘要；从用户问题+摘要提取具名机制术语，把问题分解为2-4个具名未知量（本集：损失算子、监督信号构造、跨任务泛化）
- 用这些确切术语对已抓取语料做定向search_evidence，记录命中的evidence ref与字符区间
- 只hydrate命中区间及其相邻区间，核验该未知量的机制细节
- 对仍未覆盖的未知量换用其具名术语（基准名、消融名、审计名）再检索一轮并hydrate对应区间
- 每个未知量均有原文区间证据后停止检索，成稿并显式标注未核出的数字

## Stop conditions
- 问题的每个具名未知量都已映射到具体evidence ref与字符区间的原文内容
- 检索连续miss且确认术语在正文中是转述/同义改写时，回退到章节目录或顺序分页

## Verification
- 成稿中每条机制/数字引用都能指回具体evidence ref与字符区间
- 未能从原文核出的数字显式标注'未核'，不与已核内容混排

## Counterexamples
- 文档一次抓取可完整读完：直接全读并分析，无需检索定位
- 问题是全局性/综述性（总结全文、找所有缺陷、列全部引用）：需要完整遍历，关键词定向会引入抽样偏差
- 摘要中的机制术语在正文中是转述而非原词：检索miss时应改用章节结构线索，而非继续换词检索
- 未知量在浏览前无法具名（需先通读才知道要找什么）：顺序分页是合理起点
