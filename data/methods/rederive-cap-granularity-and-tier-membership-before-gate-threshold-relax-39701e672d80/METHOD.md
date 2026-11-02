---
method_id: rederive-cap-granularity-and-tier-membership-before-gate-threshold-relax-39701e672d80
name: rederive-cap-granularity-and-tier-membership-before-gate-threshold-relaxation
description: 用户或上一轮断言『任何分批都无法通过、是否放宽门限』时，第一未知量不是新门限取值，而是门在当前代码里的真实口径：按累计还是按单路径计量、是否按资产类别分级、点名文件是否已落入更大上限的类别白名单。先用错误码后缀族 grep 实现（多个数值上限并立当场证伪『单一累计门限』模型），直读 cap 解析函数与类别前缀表做成员归属判定，再分别对逐路径上限与材料总上限核算。结论常是无需放宽：剩余超量若属总材料上限，正确动作是移走在途材料而非改门。
aliases: 放宽门限前先看门怎么分级, 超限就说调上限？先查按文件还是按总量, 审查准入体积卡死要不要提门限, 先核实门限口径再谈放宽, 大文件过不了审查门是不是该改上限
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:fb85cea0-beb4-424d-b482-2819180ee46f:1803:9e72e244aa864a69b43b
evidence_refs: learning:learn:afe77c4e7fc3
created_at: 2026-11-01T10:14:05.388992+08:00
updated_at: 2026-11-01T10:14:05.388992+08:00
---
## Trigger
用户/上一轮以『体积超限、任何分批方式都无法通过』为由征询是否放宽某个准入/审查门的门限（门限变更决策类问题），而该断言的门的计量口径未被本会话从当前代码重新核实过

## Discriminator
对门实现的一次 grep 即可见错误码后缀分类：同一前缀下并列多个不同数值上限（如 material_diff>400000 与 material_acquire>4000000、测试断言锁定的多档 cap）——这当场证伪『单一累计门限』模型，并指出存在按路径类别解析上限的函数与前缀白名单等待直读；后续任何按『累计字节』做的枚举都在回答一个已被证伪的问题

## Short path
- 定位仓库根（pwd + git rev-parse --show-toplevel），把后续动作收敛到门实现文件
- grep 门模块的错误码字符串族：从后缀并存认出分级结构，下一个未知量=cap 如何按路径解析
- 直读 cap 解析函数 + 类别前缀表/常量表，判定点名的超大文件是否命中更大上限的类别（成员归属判定）
- 对命中类别的文件逐个实测 per-path diff 字节对比适用上限（一条命令），确认逐文件可过
- 再对材料总上限核算（committed delta + worktree 等），定位剩余超量属于哪个 cap；按 cap 归属给动作（如移走在途改动），而不是动门限

## Stop conditions
- 已从当前活树源码取得 cap 解析函数、类别表与总上限，且对每个点名文件完成『适用上限+实测字节』配对核算
- 文件不属于任何特殊类别且超默认上限，或超过最大类别上限：分级模型救不了它，此时才进入门限变更/拆分讨论

## Verification
- 结论中每个 cap 值与类别归属都来自当前活树定义（常量名+调用点），而非注释、旧 release 快照或上一轮记忆
- 若声称服务已用新逻辑，明确区分『进程 git_head 证明版本』与『门真实生效』——后者只能由一次实测受理确认，不凭 git_head 宣称已通

## Counterexamples
- 门只有一个无后缀的裸常量上限、无任何类别白名单：『单门限』模型为真，可直接进入放宽权衡，不必做分级考古
- 门限是用户可配置项（env/设置）而非代码常量：直接回答取值权衡即可，无需读实现
- 本会话回执刚读过同一 cap 解析函数且带内容身份标识：按既有事实裁决，不重读源码
