---
method_id: verify-code-claims-via-receipt-vocabulary-and-cheapest-oracle-7ac52f1f87bb
name: verify-code-claims-via-receipt-vocabulary-and-cheapest-oracle
description: 审计另一 Agent/文档对代码库的断言（引用源码行为、repo 状态、基线 commit）时：先把每类断言映射到最廉价权威 oracle（repo 状态=一条 git 命令；行为断言=精确源码区间），搜索词只取自先前回执与被审 artifact 已出现的真实词汇，不凭空编造标识符；零命中回执即该名不存在的权威负证据，最多一次即停，改读最后锚点注释的邻域，并沿注释点名的机制名词（如 obligation gate）追到权威实现；断言与代码语义逐边界比对后输出带 file:line 凭据的审查结论。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5537a656-3b5b-4e20-ab72-bc23c5f26238:0:16fcb2fc7a22ffd20cec
evidence_refs: learning:learn:3c726691e644
created_at: 2026-10-11T08:56:59.659644+08:00
updated_at: 2026-10-11T08:56:59.659644+08:00
---
## Trigger
收到『审查/核实另一 Agent 或文档对代码库事实的断言』的任务，断言涉及源码行为、repo 状态或基线版本，需要逐条验证后才能给出审查意见时。

## Discriminator
进入搜索前回执已暴露判别事实：(a) 早先搜索回执已列出 engine.py 真实标识符（_cancel_reason、_run_end_reason、_background_cancel_reason）；(b) 零命中回执本身即证明所猜标识符不存在的权威负证据；(c) 该仓库注释承载机制词汇，锚点注释（engine.py:2532-2533『未结算 background children…session-level cancel hook』『正常 completed 已由 obligation gate 保证结算』）会点名权威机制。三者当时即可把『机制叫什么名』的枚举缩成『读已定位锚点的邻域』。

## Short path
- 从被审 artifact 提取可证断言清单，给每类断言指定最廉价 oracle：repo 状态/未提交→git status 一条命令；基线锚点→git log -1 与文档自报 commit 比对；行为断言→精确源码区间。
- 行为断言只用回执或 artifact 中已出现的词汇搜索（cancel/run_end/background children），命中锚点注释后直接读其邻域行区间。
- 注释若点名未知名机制（如 obligation gate），沿该名词补一次搜索定位权威实现（engine.py:2411/2417）。
- 把断言原文与代码语义逐边界比对并精化（如『正常结束取消异步 child』→『running 子任务被取消；terminal-but-unread 由 obligation gate 结算、不阻塞 final』），写出每条 ✅/❌ 均带 file:line 或命令回执的审查。

## Stop conditions
- 每个 load-bearing 断言都已有命令回执或源码行区间支撑 → 停止核查，开始写审查意见
- 同一未知量连续两次零命中 → 立即停止猜名循环，转为读取最后锚点邻域

## Verification
- 最终报告中每条 ✅/❌/精确化判定都对应可回放的 file:line 或命令回执
- 所有搜索词可追溯到先前回执或被审 artifact 原文，无凭空发明的标识符
- 断言语义在边界条件上比对过（如 running vs terminal-but-unread），而非只匹配关键词

## Counterexamples
- 搜索语料是自然语言文档/网页：精确短语零命中不代表不存在，换措辞合法，标识符精确性不适用
- 目标代码无注释无邻近命名（混淆/生成代码）：词汇锚点法失效，需结构/callsite 层面的宽发现
- 断言涉及源码不可判定的运行时行为（真实 provider、crash 注入）：源码锚点无法裁决，须实证测试而非引用行号
- 被审 artifact 已自带精确 file:line 引用：直接读那些行，再搜索是浪费
