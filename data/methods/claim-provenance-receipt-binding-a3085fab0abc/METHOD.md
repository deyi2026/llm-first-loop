---
method_id: claim-provenance-receipt-binding-a3085fab0abc
name: claim-provenance-receipt-binding
description: 终稿裁决中每条标注『属实/已核/源码实证』并引用外部来源（官方文档、上游源码、规范）的论断，必须绑定到本次 trace 中一条成功回执（read/fetch/query 的返回内容包含所引引文或事实）。回执为失败（404、UA 轮换耗尽、搜索只返回无关噪音）或引文零命中时，该论断只能降级为『未核实 prior + 前置验证门』；禁止引用任何未在工具结果中出现过的文件名、函数、错误字符串或行号。本集实例：browser.pdl 两镜像与 domain.js 连续 404、bing 搜索全噪音后，终稿仍写『从 Chromium 主干源码核到实证（browser_handler.cc…）』并引用 trace 中不存在的错误串。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4dca8b27-b04e-4081-8690-f0d58c85ec34:191:df8cfd38d779f1a66e53
evidence_refs: learning:learn:16f6c6e3dcaa
created_at: 2026-10-05T23:35:38.875933+08:00
updated_at: 2026-10-05T23:35:38.875933+08:00
---
## Trigger
撰写对代码/设计/外部分析的核查裁决或审计结论，终稿含针对外部来源的 provenance 标注，且本次 trace 中存在对这些来源的失败抓取或无效搜索回执。

## Discriminator
对每条承重论断做回执检查（只用当时已可见事实）：是否存在状态为 success、且返回内容包含所引引文/事实的回执；失败回执或引文零命中即否定『已核实』标签。本集判别事实：三次显式 404 失败回执（已轮换 3 个 UA + curl 失败）+ 一次垃圾搜索 + 全部成功回执中均无所引 browser_handler.cc 错误字符串。

## Short path
- 列出终稿中每条承重论断的被引来源与引文
- 逐条在 trace 中定位回执：成功且内容含引文 → verified；仅有失败回执或零命中 → unverified-prior
- unverified 且承重：删去未取回来源的引用，改为显式验证门（spike/实测），并把依赖工作排在其后
- 终稿自检：所有『已核实』句逐条与已取回内容 string-match，无匹配即改写措辞与标签

## Stop conditions
- 每条裁决句要么由成功回执支撑，要么被显式标注为 prior/未核实
- 所有承重且不可核实的论断均已转为下游验证任务，不存在无回执的 verified 标注

## Verification
- 机械：引文字符串必须能在某条成功回执的返回内容中 string-match
- 机械：verified 标注数 ≤ 含对应引文的成功回执数
- 抽检：任何被引文件名/函数名/错误串在 trace 中存在成功取回记录

## Counterexamples
- trace 中已有成功回执且内容含引文（如本集对设计文档与 qualification 脚本的 read_file）→ verified 标注合法，不降级
- 论断非承重（背景细节）→ 标『未核实、不阻塞』即可，不必造验证门
- 验证手段本就是任务下游实验（如已排期的 S0 spike）→ 可按假设陈述，但仍不得附未读来源的引文
