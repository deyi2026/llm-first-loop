---
method_id: decide-on-findings-from-original-receipt-not-self-paraphrase-53bc4b86b1f4
name: decide-on-findings-from-original-receipt-not-self-paraphrase
description: 对第三方（reviewer/子代理/门禁）问题清单做逐条修/弃决策时，任务状态快照或审计 md 里的清单常是自己此前手写的转述（author=model、semantic_verified=false），会静默替换或虚构条目。裁决前先按快照引用的原始回执逐字取清单，diff 出被改写条目并向用户披露；再对承重断言做最便宜代码核验（grep 精确符号/行号即可证伪『未使用/缺aria』类说法），然后才给裁决。evidence 引用直达真值，也免去为找派生文档的全盘目录枚举。
aliases: 转述对不上先查原始回执, 评审意见按原文核对再定修不修, state 摘要别当审查真值, 自己总结的结论可能被自己改写, P2 清单以 reviewer 原始回执为准
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1ee6738f-0a1e-46fa-9522-fd9f35a8933a:168:84e012bb68525352185e
evidence_refs: learning:learn:8ccebc532be2
created_at: 2026-10-27T16:37:48.841176+08:00
updated_at: 2026-10-27T16:37:48.841176+08:00
---
## Trigger
用户要求对一组来自第三方（reviewer/子代理/CI 门禁）的发现/问题逐条给出修/弃等决策，而手头只有此前自己写入的摘要（任务状态、审计文档），该记录带 author=model / semantic_verified=false 类来源标记并同时引用原始回执

## Discriminator
摘要自身的 provenance 元数据已声明它是模型手写、未经语义校验的转述，且给出原始回执的 evidence:// 引用；当每条裁决取决于『条目到底是什么』时，转述不具决策资格

## Short path
- 读任务状态一次；记下 author/semantic_verified 标记与被引用的原始回执 evidence ref
- 裁决前先取原始回执，逐字抄录问题清单；与转述 diff，向用户明确列出被替换/虚构/多出的条目
- 对原始条目里决定裁决的断言做最便宜核验：在冻结工作树 grep 精确符号/行号（如『queueZh 未使用』→该符号仍在用即证伪；『缺 aria-label』→按钮有可见文本即不成立）
- 按核验结果映射裁决：不可恢复的数据损失→必修；同批文件一行级对齐→顺带修；设计取舍/纯文案→明确放弃并给成本理由
- 每条建议同时锚定到逐字原文+一条代码核验回执后停止；提醒改动会作废冻结指纹、需重走审查

## Stop conditions
- 原始回执不可得且无其他权威副本→带 caveat 给决策或建议重跑审查，不再翻找派生文档
- 清单是机械逐字抽取（结构化 JSON）无转述风险→直接进入代码核验
- 所有建议条目已同时具备逐字原文锚点与代码核验回执

## Verification
- 重读原始回执一次，确认引用的每条与原文逐字一致
- 每条『存在/不存在』的代码断言都有对应 grep/read 回执
- 若此前轮次已给过基于转述的答案，确认本次答案显式披露了差异

## Counterexamples
- 原始回执已过期/丢失，转述是唯一记录：应以 caveat 决策，不因方法阻塞
- 决策不依赖条目身份（全修或全弃），取原文收益趋零
- 第三方输出本身是结构化逐字数据、摘要为机械拷贝，无改写风险
- 核验成本高于决策收益的纯文案微调，只抽查会让裁决翻盘的条目
