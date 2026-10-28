---
method_id: pin-consumption-surface-before-model-facing-format-refactor-af0ec3de7fad
name: pin-consumption-surface-before-model-facing-format-refactor
description: 用户质疑某类供模型消费的工件（方法卡/注入提示/记录薄卡）『格式别扭、用不起来、要重构』并要求先讨论时，第一个未知量不是文体之争，而是模型在决策点实际看到什么：记录 schema、检索时薄卡的渲染文本、既有使用测量（深读率/A-B）。本集 19 次调用中约 6 次耗在与题无关的渲染代码和跨子系统元数据 grep（task_applicability/卡龄等生命周期样板 token 每个触碰记录的子系统都出现），另有 2 次按平面路径猜 methods/<名>.md 而 ls 已显示为 <名>/METHOD.md 目录结构。捷径：本 run 自己的检索回执就是薄卡活样本；首轮命中点名的 eval 协议/注入卡/store.card() 是直连『模型所见』的 provenance 边，先沿它们把三面证据钉死再谈改法。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f6f1dadc-64d2-4789-bbac-44b68f133442:38:0a636719c94a8bf17504
evidence_refs: learning:learn:5662e487bc84
created_at: 2026-10-19T23:48:13.896691+08:00
updated_at: 2026-10-19T23:48:13.896691+08:00
---
## Trigger
用户或评审提出某类模型消费的工件（方法卡、注入提示文本、记录卡）格式别扭、匹配/使用失败、需要重构，且要求先讨论或先摆事实再动代码时；或需要判断『匹配失败发生在模型看到内容之前还是之后』时。

## Discriminator
两条在当时已在手的事实可立即缩小搜索：① 本 run 自己收到的检索回执本身就是该工件薄卡的活样本，可零成本逐字段对比两类记录的渲染差异（method 命中带 ref/status/卡龄/task_applicability+description，经验类带 scenario 线索）；② 首轮搜索命中已点名直连消费面的文件（A/B eval 协议目录、注入卡源文件、store 的 card()/MethodRecord 定义）。反之，status/task_applicability/卡龄这类生命周期样板 token 在每个触碰记录的子系统都会出现，对它们做全库内容 grep 只会枚举代码库而不会枚举答案。

## Short path
- 把『格式好不好用』改写成三个可查未知量：记录 schema 有哪些字段；模型在决定是否深读那一刻看到的文本是什么；有无已测的使用差距（深读率/A-B 结果）。
- 用刚收到的检索回执当薄卡活样本，逐字段对比两类工件的渲染差异（零工具成本）。
- 沿首轮命中已点名的文件各读一次（eval 协议、注入卡、store.card()/记录类定义），钉死 schema 与渲染路径，顺带摘录其中的实测注释/测量数字。
- 读一张对照类别记录的原文（如经验卡 frontmatter），确认字段差异是 schema 级而非文笔级。
- 若需『混装』证据：先 ls 目录，按列表推导实际路径（<名>/METHOD.md）再读代表样例，不猜平面文件名。
- schema、决策点可见文本、使用测量三面均有源码或回执级证据即停，输出事实、更新后的判断与待用户裁决的分歧。

## Stop conditions
- 三面证据（schema 字段、决策点渲染文本、使用测量）均已从渲染/schema 源码或本 run 回执钉死且相互一致；
- 用户明确表示只要观点 brainstorm、不要证据调查。

## Verification
- 回答中每条『模型看到/看不到某字段』的断言都能指到具体渲染代码行或本 run 的回执样本；
- 引用的深读率/A-B 数字注明出处（代码注释或评估产物），未复测时明确声明沿用旧测值。

## Counterexamples
- 问题对象就是元数据机制本身（如『卡龄降权为何未生效』）：该 token 此时是类型专属信号，对它 grep 是正确动作，不应套用本卡；
- 工件只被整体水合、不存在薄卡决策点：thin-card 分析没有对象，schema+全文即全部消费面；
- 检索回执是调试专用格式、与生产渲染路径不一致：回执当活样本会误导，必须直读生产渲染器；
- 用户明说『别查了先聊』：跳过调查直接进入讨论。
