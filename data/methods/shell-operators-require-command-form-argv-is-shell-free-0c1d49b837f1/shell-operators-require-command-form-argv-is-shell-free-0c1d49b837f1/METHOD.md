---
method_id: shell-operators-require-command-form-argv-is-shell-free-0c1d49b837f1
name: shell-operators-require-command-form-argv-is-shell-free
description: 执行工具同时提供 command（字符串、经 shell 解释）与 argv（数组、不经 shell）两种互斥调用形态时，形态由命令语法决定而非习惯：含 &&、||、|、>、$() 等 shell 操作符或需组合多条命令的调用必须走 command/shell 形态，否则操作符被当作字面参数传给可执行文件（git 把 '&&' 当 revision 报 ambiguous argument）；纯单命令调用用 argv 更安全。判别材料动手前已在场：任务合同写明 argv 形态并附 'no command field'，回执逐条标注 exec_mode。若调用是受管一次性动作且冻结 admission target 已钉死形态，则形态合规优先，不得为组合语法改形。
aliases: &&被当成参数传给了git, 报错ambiguous argument &&, 组合命令该用command还是argv, exec_mode argv和shell怎么选, shell操作符在argv里失效
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:9d50aa4b-460d-44e4-bf33-37e59c4cb684:24:c008573971e2ad3b1a62
evidence_refs: learning:learn:7456da48bf6c
created_at: 2026-11-19T19:32:29.712649+08:00
updated_at: 2026-11-19T19:32:29.712649+08:00
---
## Trigger
execute_command 类工具存在 command/argv 双形态，而当前待执行命令包含 shell 操作符（&&、||、|、>、$() 等）或需要组合多条命令

## Discriminator
动手前即可用的事实：用户合同在指定 push 用 argv 数组的同时明说 'no command field'——这暴露工具存在两种互斥调用形态，且 argv 数组语义上就是不经 shell 的直调，shell 操作符只能是普通参数；因此含 && 的核验命令注定在 argv 形态下失败，必须走 shell/command 形态。

## Short path
- 先从任务合同、工具 schema 或历史回执的 exec_mode 标注确认执行工具的双形态合同
- 机械扫描待执行命令：是否含 && || | > $() 等 shell 元字符、是否组合多条命令
- 含元字符→用 command/shell 形态一次执行；纯单命令→用 argv 形态
- 受管/受闸动作若被冻结 admission target 或任务合同钉死 argv，则该动作保持 argv，把组合核验拆成独立的不受闸 shell 调用
- 执行后核对回执 exec_mode 与退出码，满足该步未知量即停

## Stop conditions
- 所选形态一次执行成功，回执退出码与输出满足该步未知量
- 命令为纯单命令且无 shell 元字符——argv 直接可用，不存在形态问题

## Verification
- 回执 exec_mode 字段与所选形态一致
- 含 && 的命令在 shell 形态下应返回各段命令的输出，而不是把 '&&' 当参数的 'ambiguous argument' 类错误

## Counterexamples
- 受管一次性动作（如审查 PASS 后的 push）的冻结 admission target 或合同钉死 argv 时，不得为组合语法改用 shell 形态——形态合规优先于便利（由 prevalidate-invocation-form-before-consuming-one-shot-qualification 卡管辖）
- 命令是单条可执行调用、无任何 shell 元字符时，argv 是正确且更安全的选择，不应套用'一律走 shell'
- 执行工具只有单一调用形态（无 command/argv 之分）时，本方法不适用
