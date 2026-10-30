---
method_id: form-named-block-decompose-atomic-write-then-separate-validate-ec980d278760
name: form-named-block-decompose-atomic-write-then-separate-validate
description: 带准入/安全闸的宿主里，用 shell 落盘多行生成内容或做就地校验被 blocked、且回执点名的是命令形态（heredoc、任意管道直连解释器执行、requires_split_commands）而非动作目的/权限时：剔除该形态、语义等价地分解重发——printf 行表写文件、以文件为参数的独立语法校验、副作用单独成条；不重试同形态，也不先走提权。目的/权限类阻断（需独立审查回执、灾难性内容判定）不得用改形态规避，必须走审查/提权通道。本集两次实证：heredoc 被拦后改 printf 成功，但写 CI yml 时仍先用了管道接解释器再次被硬阻断——第一次被拦后就应把『生成内容一律先落盘、再独立校验』泛化到全部落盘场景。
aliases: heredoc 被闸拦了怎么写文件, 管道接 python 校验被硬阻断, 先落盘再单独跑语法检查, hook 脚本写不进去, 命令被点名形态阻断
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:2020:595dba45c79bf4fba996
evidence_refs: learning:learn:0cc57e25bcb3
created_at: 2026-10-29T23:28:46.064653+08:00
updated_at: 2026-10-29T23:28:46.064653+08:00
---
## Trigger
需要用 shell 把多行生成内容（hook 脚本、CI 配置等）落盘或管道进解释器校验，且宿主存在命令级准入/安全闸，同会话中简单命令与 && 复合命令此前已被放行

## Discriminator
阻断回执命中的是命令结构特征而非内容或权限：如 compound_protected_shell_requires_split_commands、『任意管道直连解释器执行』；而同会话同目的的简单形态命令已放行——闸按形态放行，不是按任务禁止，回执本身就是可接受重发方式的规格说明

## Short path
- 落盘直接用已放行/被提示的形态：printf '%s\n' 行表重定向到目标文件（或专用写文件工具），不构造 heredoc
- 校验独立成条、以文件为参数而非管道：bash -n <file>；python3 -c 加载该文件做 yaml/语法解析
- 执行位、安装等副作用拆成独立命令，各自拿回执
- 若仍被拦：只读回执点名的形态词，剔除该特征重组命令、语义不变；同形态不重发、不盲目换参数

## Stop conditions
- 文件已落盘且回读或独立校验通过（SYNTAX_OK / YAML_OK 类回执）
- 阻断指向目的、权限或不可逆内容（要求独立审查 PASS、灾难性行为类）——立即停分解路径，转 review_admission / escalation_request，不得以改命令形态绕过

## Verification
- 新命令不再包含被点名形态（无 heredoc、无管道直连解释器）
- 独立校验命令自身 exit 0 并有明确 OK 输出
- 落盘产物行数/关键行与意图内容一致

## Counterexamples
- 阻断原因是权威/目的类（规则要求先取得独立审查 PASS 回执、或判定为破坏性内容）：改写命令形态属于绕闸，必须走审查/提权通道
- 无命令级准入闸的环境：heredoc 合法且更可读，分解是纯成本
- 超大生成物：printf 行表不实用，应换写文件工具或分块追加，而非机械套 printf
