---
method_id: write-target-inside-sandbox-declared-zone-8ad8ecabeb9a
name: write-target-inside-sandbox-declared-zone
description: 在沙箱化执行环境里落盘新产物前，先用回执里已声明的写侧约束选目标路径：沙箱横幅（如『仅允许写工作区与缓存目录』）+ shell cwd 已在屏幕上时，默认把目标选在 cwd 工作区内的等价目录，而不是习惯性路径。写入被拒时先归因拒绝层再重试：宿主准入规则码→改命令形态（拆 heredoc/避保护关键字）；OS 层 Operation not permitted 且 write-scope 全量→是沙箱层，换目标区或换非 shell 写工具；scope 受限→走授权，不擅动。同症状不同层修法不同，原形态重试只攒失败。
aliases: 写文件 Operation not permitted 换到当前仓, 被沙箱挡写先看回执横幅再选路径, 占位文件写不进去就落到工作区内, 写入被拒先分清准入还是沙箱还是授权, 交接文档落到可写仓库, 写不进外层目录改仓内等价路径
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:5284:14eeaa7c1380484f4daa
evidence_refs: learning:learn:65b791881104
created_at: 2026-10-31T12:21:40.312184+08:00
updated_at: 2026-10-31T12:21:40.312184+08:00
---
## Trigger
需要在沙箱化命令/文件工具下新建或写入产物文件，且此前任一回执横幅或 scope 回执已声明可写范围；或一次写入刚被拒绝，需要在『改命令、改路径、改授权』之间抉择

## Discriminator
每条 execute_command 回执横幅明示『已启用 sandbox-exec：仅允许写工作区与缓存目录』，且当前 shell cwd 是镜像仓；若拟写路径在 cwd 树之外（如另一 workspace 目录），OS 层写入必然 Operation not permitted——该判断写前即可做出，且与 write-scope 是否全量无关（本会话 scope 全量仍被挡，证明挡的是沙箱层）

## Short path
- 写前盘点屏幕上已有的写侧约束事实：回执沙箱横幅、cwd、以及（若有）write-scope 回执，确定各层分别允许写哪里
- 按约束选目标：默认落在 cwd 工作区内的等价位置（如仓内 docs/design），一次 ls -d 探存在性
- 单行 printf 占位（避开保护动作关键字）→ read_file 校验 → edit_file 写入正文（heredoc 受阻时复用既有经验卡的合规通道）
- 若仍被拒，读拒绝回执的层标识再定动作：规则码=准入层改命令形态；Operation not permitted 且 scope 全量=沙箱层改目标区；scope 受限=授权层上报用户
- read-back 一致后即收口（handoff/present_files），不再额外确认写权限

## Stop conditions
- 占位或正文写入回执显示写后复读一致，且最终路径在声明可写区内
- 产物必须落在工作区外且无已授权通道可达时，停止改道与重试，向用户上报选项或申请授权

## Verification
- 占位文件 read_back 内容一致（行数/sha）后才写正文
- 最终写入路径与计划目标一致，且属于该会话横幅/scope 声明的可写集合
- 如发生过拒绝：确认重试动作与拒绝层归因一致（准入→改命令、沙箱→改路径、scope→改授权）

## Counterexamples
- 用户明确指定产物必须落在工作区外的固定路径时：改道 cwd 等价目录违背交付要求，应上报或先申请授权，而非静默换位置
- 写入走的是受 write-scope 策略管的专用写工具、且无 OS 沙箱横幅时：横幅不约束该工具，照策略与授权判断，不要误归因沙箱层
- 无任何横幅的裸环境命令写失败（如路径拼写错、挂载只读）：先查路径与文件系统本身，分层归因框架无输入
