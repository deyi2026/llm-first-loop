---
method_id: reverify-claimed-numbers-via-structural-recompute-and-value-compare-aa187f0ae1ae
name: reverify-claimed-numbers-via-structural-recompute-and-value-compare
description: 本集先前消息写出了一张『已核事实』表（含具体计数、状态分布、文档行号引用），但会话中并无对应工具回执。收敛指令触发全量重审：逐条重算每个数字，抓出 5 处漂移；过程中还暴露两类假验证——(1) 全文 grep 统计字段时把正文散文提及也计入；(2) 数字校验脚本只查『数字串是否出现在正文』，错值全部假通过。方法核心：任何『已核/verified』断言必须绑定当会话回执；重算须用与记录真实结构一致的解析器（frontmatter 只解析 frontmatter、JSONL 用 json 解析）并做数值级相等比对；查无日志佐证的记忆性断言降级为 unverified/lesson，不得计入 verified 集合。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:8432bab4-9ec8-4407-a69c-0cd2c90dce64:1191:4f9377a65720514a7d0a
evidence_refs: learning:learn:c2dcf4ab4d6c
created_at: 2026-10-15T14:31:50.243605+08:00
updated_at: 2026-10-15T14:31:50.243605+08:00
---
## Trigger
会话中已存在（通常是自己先前输出的）『已核/verified』具体断言清单——计数、状态分布、行号级引用——但按会话历史对照找不到对应工具回执；或正要撰写此类断言表、或要为成稿编写数字校验脚本时。

## Discriminator
两条当时即可见的事实：(1) 断言表中的数字与行号在会话工具回执中逐条对照后存在缺口——声称的 provenance 与实际回执不符是当场可核的；(2) 记录的真实结构已在卡片样例中暴露为 YAML frontmatter / JSONL，因此整文件 grep 的计数输出里混入非枚举散文值（如以字段名开头整段句子）即证明访问器与记录结构不匹配。

## Short path
- 把先前断言表展开为有限逐条清单（数字/状态/行号），先标注哪些条目没有当会话回执；定义未知量=每条的真值。
- 对每条用与记录结构一致的访问器重算：frontmatter 只解析 frontmatter 字段、JSONL 用 json 逐行解析，不用全文 grep 做权威计数。
- 成稿数字与重算值做数值级相等比对；禁止『数字串是否出现在正文』式的自洽存在性检查——它只验证文章与自身一致。
- 无回执且相关日志（异常/自纠记录）查无实据的记忆性断言，降级为 unverified 或 lesson，不写入 verified 集合，也不作为论点支柱。
- 漂移修正后把新数字同步传播到所有产物（正文、配图、脚本期望值），重跑校验至零 mismatch 即停止；后续新增记录（如本次新存的 lesson）会改变分母，需再跑一次而非沿用旧值。

## Stop conditions
- 交付物中每个数量断言要么映射到一条当会话工具回执，要么显式标注 unverified；
- 修正后的数字在正文/图/校验脚本三处一致，且校验以数值比对方式通过零 mismatch。

## Verification
- 用结构化解析（frontmatter/JSON）重算全部计数，与最终成稿逐数 diff 为零；
- 逐条检查：每个标 verified 的断言能指回一条真实存在的工具回执；
- 向校验脚本故意注入一个错误数字，确认它能被抓住——存在性检查类脚本会在这一步暴露假通过。

## Counterexamples
- 数字已在本会话某条工具回执中直接展示 → 引用回执即可，重算是冗余动作；
- 纯定性陈述、无数值内容 → 没有可重算对象，只需标注来源，不适用本卡；
- 低风险闲聊性数字、重算成本远超断言价值 → 标 unverified 即可，不必强制重算；
- 共享可变资源存在并发写者时的终局性断言 → 属『成稿时重读权威记录并加时间戳』的场景，本卡不解决时序新鲜度问题；
- 记录结构未知、仅做候选定位（非权威计数）时 → grep 作为发现手段仍合理，只是不得当计数器用。
