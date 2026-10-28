---
method_id: include-executable-verification-line-when-depositing-method-cards-91668dcab954
name: include-executable-verification-line-when-depositing-method-cards
description: 向带参数校验的沉淀库提交 method/experience 卡时，校验器要求卡内含一行『可执行的当前性验证动作』（如 grep -n <关键字> <路径> 确认行仍在，或复现命令+期望结果），否则参数错误拒收。纯行为/呈现规范类卡最易漏：本集同批两张卡，含结算对比核验内容的通过，纯派发格式规范的被拦，补一行 grep 后单次重提即过。提交前自检卡 body 是否含可执行验证锚点；被拒时错误回执本身就是补写模板，只补一行重提，勿重构卡片。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:54ba6da3-7041-4b6f-8aac-8df1e542850f:332:7b75e88492a9d498b9c1
evidence_refs: learning:learn:40d3c2402d34
created_at: 2026-10-22T22:48:45.595467+08:00
updated_at: 2026-10-22T22:48:45.595467+08:00
---
## Trigger
通过 save_method_candidate 或同类带参数校验的记录工具沉淀 method/experience 卡，尤其卡内容为行为纪律、流程步骤或呈现格式类规范（没有天然可运行的检查步骤）

## Discriminator
提交前即可见的事实：卡 solution/body 中不存在任何可原样执行的验证锚点（无 grep/复现命令+期望结果），且卡结论锚定的是可漂移的当前工件（文档行号、规则条款、代码路径）。对照信号：同批含『结算/实测对比』类核验步骤的卡已通过——缺此锚点的纯规范卡正是被『卡内未检出可执行的当前性验证动作』拦截的那类。

## Short path
- 起草卡时列出该卡结论锚定的当前工件（设计文档章节行、规则条款、代码路径）
- 在 solution/body 写一行当前性验证：『当前性验证：grep -n <关键字> <路径> 确认行号仍存在』或『复现：跑 <命令> 应得 <结果>』；纯行为方法可把验证锚到承载该规范的文档行
- 提交；若被参数校验拒绝，按回执给出的模板原样补该行，单次重提
- 回执 success（返回 stable ref/content_hash）即停，不追加冗余验证行

## Stop conditions
- 回执 success 且带稳定引用，即完成，不再改卡
- 按回执补一行重提后仍失败 → 读回执引用的规则/演进原文，定位真正缺失的字段，不盲目第三次重试
- 卡已含可执行核验步骤且首提通过 → 无需额外动作

## Verification
- 提交前自检：卡内至少存在一条可原样复制执行的命令行（含路径与期望结果）
- 验证行本身可执行：grep 应命中且行号仍存在
- 复现校验器行为：不含验证行的提交应得『卡内未检出可执行的当前性验证动作』类参数错误，且回执引用定义该校验的规则/演进记录（本集为一条卡片校验类 EVO）

## Counterexamples
- 卡本身已含实测/对比核验步骤（如结算产物 vs 声明写集对比）且首提已通过 → 不要为凑格式再堆重复验证行
- 目标存储无参数校验（普通笔记、自由文本文件）→ 强加验证行只是噪音
- 拒绝原因是别的字段（如归档门要求真实工件路径而非记录 id）→ 先读回执点名的是哪类缺失，勿条件反射地加 grep 行
- 治理规则演进替换/移除该校验后 → 以当前回执行为为准，本卡前提失效
