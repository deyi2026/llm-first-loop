---
method_id: falsify-inherited-progress-claims-by-lifecycle-level-1c8747be4cef
name: falsify-inherited-progress-claims-by-lifecycle-level
description: 续跑/复盘/拷问上一轮总结时，先不质询计划本身：把总结里的进展断言按工件生命周期分级（已写/已提交/已推送/已部署生效），每级只在其权威面做一次证伪查询——已写→工作树精确符号锚点 grep+文件 git status（0 命中即证伪，不是『丢了』）；已推送→ls-remote 远端真值；已生效→按服务/通道的部署回执 git_head。跨级压缩的复合断言（如『已写未提交』）是最高收益证伪目标；共享工作树上『已写』被证伪时查并发写者（如他人 git add -A 正在跑）解释消失，并把『不在共享 main 树留未提交代码』升级为写边界建议；单通道核到的『已生效』必须标注效度边界。证伪完成后再用存活前提重构问题与建议。
aliases: 上轮说改了没提交 先grep工作树再信, 说没推送先ls-remote对远端真值, 复盘先纠上轮事实再提问, 生效结论分服务看部署head, 共享树没提交的代码会被并发会话卷走
status: candidate
source_model: deepseek/deepseek-flash
source_episode_refs: episode:7e91da8b-4d11-4df5-84fc-7666790cb2fb:948:fb40bce492ec58e6cd09
evidence_refs: learning:learn:0e20c801c0a2
created_at: 2026-11-09T16:49:16.685697+08:00
updated_at: 2026-11-09T16:49:16.685697+08:00
---
## Trigger
续跑、复盘或被要求拷问上一轮总结/交接时，总结含工件进展断言（已写、已提交、已推送、已排队重启、已生效），且存在可查的权威面（工作树、远端 ref、部署/服务状态回执），环境可能有并发会话或多通道部署

## Discriminator
断言措辞点名生命周期级别，每级对应唯一能证伪它的权威面：written→唯一符号锚点在工作树的 grep 命中数 + 该文件 git status；pushed→git ls-remote（远端真值，不信记忆或本地 origin 引用）；deployed/effective→逐服务部署回执的 git_head/generation，且一通道通过不外推到其他通道；跨级压缩断言优先拆开逐级核

## Short path
- 枚举上轮总结的可验证断言，按 已写/已提交/已推送/已部署 四级分类；判断与建议类内容留待质询本身处理
- 每条断言在其级别的权威面做一次窄查询，证据落到具体输出（grep 计数、ls-remote 行、回执字段）
- 『已写』被证伪且仓库为共享 → 查一次 coordination/并发会话状态，把消失解释为并发写者行为，并形成『写入走独立 worktree/分支』的边界建议
- 『已生效』只在单通道核到 → 结论显式标注仅该通道，落后 head 的其他通道不算生效
- 用存活前提重构拷问问题与建议清单；被证伪项先在答复中纠正，不基于死前提提问或排计划

## Stop conditions
- 总结中每条工件级断言要么被权威面证实、可逐字指回证据，要么被证伪并已在答复中纠正
- 对外结论只用证据支撑得住的那一级表述，已写/已提交/已推/已生效 分开陈述，不再跨级压缩

## Verification
- 每条纠正都能指回一次具体查询输出（符号 grep 0 命中、ls-remote 的远端 head、服务回执的 git_head 字段）
- 『已生效』类结论均带通道/服务边界标注；共享树上若仍有未提交改动，建议中包含写边界处置

## Counterexamples
- 上轮内容是设计判断、提案或推理而非工件状态断言：没有权威面可查，直接按质询对象评估，不做证伪清单
- 当前会话的成功回执已逐字回显该值：回扫回执绑定即可（receipt-echoed 领域），不重复发起级别查询
- 『已写』断言缺少唯一可 grep 的符号锚点（无稳定标识符）：工作树 grep 无法证伪，改用文件级 diff 或向作者求证，不硬套本卡
