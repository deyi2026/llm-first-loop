---
method_id: config-why-via-referenced-design-doc-plus-code-default-29dd04a03941
name: config-why-via-referenced-design-doc-plus-code-default
description: 回答『某特性为什么默认 off/on』类理据型问题时，权威来源是一对：设计文档决策节 + 配置字段定义及其注释。首次检索 miss 的回执通常已显式列出含该特性编号的权威设计文档引用，应沿该引用直接读取，而不是换词重搜同一索引，更不要对歧义短 token（如两字母特性代号）做全库内容 grep——本集该类搜索命中 11 条 venv/CSS 单位/locale 噪声。随后用代码 grep 验证默认值与 env 接线，双源引用作答。与 resume-continuation-via-named-provenance 的 miss-receipt 引用机制同源，但触发不同（理据型配置问题 vs 极简续跑指令），并新增『问题类型→权威来源对』映射与代码侧验证组件，非重复卡。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9571992a-d742-4a48-824b-b1f635b8674f:1497:5b0531682be69f5b3495
evidence_refs: learning:learn:5cb9e909df0d
created_at: 2026-10-07T12:22:52.410362+08:00
updated_at: 2026-10-07T12:22:52.410362+08:00
---
## Trigger
用户询问某特性/开关『为什么默认 off/on/这样设计』这类理据型问题；首次 search/docs 检索未命中，而 miss 回执附带的『最近文档参考』列表中已出现与该特性对应（标题或特性编号吻合）的权威设计/需求文档引用。

## Discriminator
进入宽搜索前当时可见的两个事实：(1) miss 回执自身已列出含查询特性编号（如 FR-1）的文档标题及对应需求设计文档——工具主动给出的 provenance edge；(2) 理据型问题的答案权威在『设计文档决策节 + 配置字段定义及注释』，不在全库内容 grep。判别器成立前提：引用列表确有匹配项；无匹配则不适用。

## Short path
- 拆解未知量：涉及哪些特性、默认值定义在哪、理据在哪。
- 首搜 miss 后不换词重搜、不做全库内容搜索；从回执引用列表直接选出匹配的设计文档读取（不知路径时仅做文件名精确搜索）。
- 从文档提取决策节与开关名，grep 配置模块确认字段默认值、原注释与 env 覆盖接线。
- 以『文档小节 + config file:line』双源引用作答；文档与代码不一致时如实报告差异并停止。

## Stop conditions
- 设计文档决策节与代码默认值均已取得且相互一致 → 作答完成，停止。
- 回执引用列表中无任何与查询特性匹配的文档 → 本方法不成立，转入按精确标识符/文件名的窄搜索或合理宽发现。
- 代码默认与文档声明冲突 → 报告两处带行号证据，不强行编造统一叙事。

## Verification
- 最终答案必须同时引用设计文档小节与 config 定义的具体 file:line（含 env_bool 等接线），缺一即未完成。
- 核对文档声明的默认值与代码默认值一致；不一致要作为显式发现报告而非掩盖。
- 不得给出文档和代码都不支持的臆测理据；理据缺口（如『未写何时翻默认』）须如实标注。

## Counterexamples
- miss 回执引用列表中没有与查询特性/编号相关的文档：无 provenance edge 可沿，此时宽发现才合理。
- 问题是『当前实际是否开启/线上现值』而非『为什么默认』：文档不足为凭，必须读运行时 config/env，不得混用两类问题。
- 特性完全无文档踪迹且命名未知：应做精确标识符/文件名搜索；但仍应避免用两字母歧义 token（会命中 CSS 单位、locale、venv 包名）做全库内容 grep。
- 文档陈旧而代码近期已翻转默认：方法仍可用于定位，但结论须以代码为准并标注读取时点，不能拿旧文档当终局。
