---
method_id: protected-action-single-command-after-admission-pass-a550705bf332
name: protected-action-single-command-after-admission-pass
description: 准入闸对受保护动作（git push、发布/写侧操作等）签发 PASS 后，执行时必须把该动作作为单条独立命令提交：cd/echo/HEAD 回显/rc 采集等辅助段一律拆成前后独立步骤，不与受保护动作拼接。判别依据是 PASS 回执的 target 绑定到单一命令/动作身份，host 闸按『本次提交的那条命令』评估；多段复合体会被结构性拒绝（compound_protected_shell_requires_split_commands），与审查结论无关、重审也不解决，正确动作是按拒绝文案机械拆分后以同目标重试。只约束受保护动作；只读检查照常可拼接。
aliases: push 前审查过了执行还被拦, git push 要单独一条命令提交, 别把 push 和 cd echo 拼成复合命令, 受保护动作单独一步提交, host 闸要求拆分命令怎么处理
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:52:5fdb0bdcfab525ee1dd7
evidence_refs: learning:learn:29e270d6bda8
created_at: 2026-11-05T15:14:50.373725+08:00
updated_at: 2026-11-05T15:14:50.373725+08:00
---
## Trigger
准入/审查闸已对某受保护动作（git push、发布/写侧操作等）签发 PASS 回执，正准备通过 shell 执行该动作；或拟提交的命令串中除受保护动作外还含 cd/echo/rc 采集等辅助段

## Discriminator
PASS 回执的 target 已绑定到单一命令身份（形如 git_push:<sha>:command:<sha256>），表明闸按单条命令粒度绑定资格；把 cd、echo 'HEAD=…'、echo 'push_rc=$?' 等辅助段与受保护动作拼成多段复合命令后，回执无法绑定到这条复合体，闸按命令结构拒绝——这是形态问题而非审查问题，重审无法解除

## Short path
- PASS 回执到手后，先把执行前核对（HEAD、ahead/behind、待推提交清单）作为独立命令步骤跑完
- 将受保护动作本身作为单条命令提交（如 git push origin main），命令串中不含任何 ; / && 连接的辅助段
- 执行成功后另起独立命令做结果核对（如 rev-list --left-right --count 应为 0\t0）
- 确需多段含保护动作（如必须内联 env 或 cd）时，按闸回执自述的逐段准入通道分别提交各段，而非拼接一条复合命令
- 若已被拦：拒绝文案已给出精确修复（拆分），机械照做并以同一目标重试即可，不需要重新发起审查

## Stop conditions
- 受保护动作以单条命令执行完毕且工具回执确认成功（退出码 0、远端 ref 推进到本地 HEAD）
- 闸的拒绝原因是其他命名维度（产物/快照指纹漂移、candidate_sha256 不匹配）时，停止拆分重试，转入『PASS 后仍被同名拒』类路径处理

## Verification
- 拟提交的命令串中受保护动作独占一段：扫描确认无 ; / && 连接的其他命令
- 执行后独立核对：ahead/behind 计数归零、远端 ref 与本地 HEAD 一致

## Counterexamples
- 只读/非保护命令的例行检查（pwd、git log、git status 组合）：复合拼接合法且高效，全部拆分反而浪费轮次
- 拒绝文案指向产物指纹或快照漂移而非命令结构时，拆分命令无效，应先核验 candidate_sha256 与回执一致性
- shell 每次调用都重置 cwd 或受保护动作必须内联环境变量的环境里，裸单条命令不可用，应使用逐段准入或闸文档化的豁免机制
