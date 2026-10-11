---
method_id: resolve-self-flagged-unverified-premises-before-review-answers-c24232b01d34
name: resolve-self-flagged-unverified-premises-before-review-answers
description: 当评审/拷问问题集到来，而被评审设计文档自身含显式未核验标记项（如'细节未实跑核验'、'待定'）时，先分诊再作答：凡答案取决于这些未核验项的问题，必须先到最窄权威源（符号定义→docstring→实现）核实；核实结果可能推翻原担忧方向，须先改设计再作答（本集：inherit 实为 retrieval-only、inline_parent_messages=0，独立性由 spawn 参数直接保证，v1 担忧方向被反转）。无权威源可答的问题标 open+fallback，不得猜答。处理退化评审工具的循环属于另一既有方法，不在本卡范围。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9bd2b826-af96-4acb-87be-49c2646f1725:120:bd1e7ba8ed1eb1873443
evidence_refs: learning:learn:c65352ea0259
created_at: 2026-10-11T08:25:38.812941+08:00
updated_at: 2026-10-11T08:25:38.812941+08:00
---
## Trigger
对抗式/模板化评审问题集到来，且被评审设计文档中存在显式未核验标记项（未实跑核验/待定/assumed），其中部分问题的答案直接取决于这些项

## Discriminator
问题主题可与设计文档中带未核验标记的条目一一交叉对应（如'干净上下文是否成立'↔标记为未核验的 _inherit_parent_context 行为），且该条目存在可访问的权威源；进入分诊前，v1 设计文本中的标记与工具返回的问题清单均已可见，无需事后信息

## Short path
- 收到问题集；未知量：哪些问题能用已核实事实直接回答？
- 将每条问题与设计的未核验标记项交叉分诊；未知量：哪些答案悬在未核验前提上？
- 对命中的条目按 grep 符号→docstring→读实现的最窄路径核实；未知量：机制是否如假设运作？
- 证据与原担忧方向相反时，先修订设计（本集：独立性改由默认 inherit=False 保证）再作答
- 只回答已落地的问题；无权威源的标 open+fallback；全部分诊问题落地或显式 open 即停止

## Stop conditions
- 每条分诊出的问题要么有 cited 权威事实支撑，要么显式标为 open+fallback
- 凡核实结果与原假设相反处，设计文本已先行修订再作答
- 没有残留任何依赖未解决未核验项的作答内容

## Verification
- 原未核验项逐条落到具体 file:line 引用或进入显式 open 清单（本集：runner.py:2386/2418 retrieval-only 零注入、2401/2409 fail-open）
- 检查设计随方向翻转而版本递进（v1→v2），修订理由引用的是核实证据而非模板问题本身

## Counterexamples
- 问题取决于用户偏好/产品意图：代码核实答不了，应问用户或记 open，不得拿读码冒充答案
- 未核验项低风险、核实成本超过设计影响：写明假设+验证计划即可，不必深挖
- 权威源不可访问（闭源依赖/仅二进制）：显式做成双分支假设，不假装已核实
- 问题本可由设计中已核实事实直接回答：直接作答，不触发核实流程
