---
method_id: paste-robust-one-line-command-handoff-a416b1dd5d73
name: paste-robust-one-line-command-handoff
description: 用户手动粘贴执行助手给的命令后，shell 报『把 VAR=... 当命令名找文件』类错误：失败发生在聊天→终端的粘贴传输层（换行/续行符丢失），不是命令语义错。先用只读手段补齐重发前提：CLI 子命令签名从源码/总 usage 读取（被 fence 拦截的子命令不靠执行 --help）、可变状态（如 generation 计数器）用只读子命令探得、并核验历史上导致拒绝的前提（HEAD 含目标修复、tracked worktree 干净）；然后只发一条单行、全绝对路径、env 前缀的命令，env 使赋值即使粘贴变形也只被当作参数而非命令名。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cba0dcfa-4656-4850-921d-1fad481ce73d:1006:afbb783c81111f18acca
evidence_refs: learning:learn:e0bf4813feca
created_at: 2026-09-20T17:36:30.401747+00:00
updated_at: 2026-09-20T17:36:30.401747+00:00
---
## Trigger
用户把助手给出的多行/带续行符命令复制进自己的终端执行后，shell 报错把环境变量赋值 token（VAR=value）或行首 flag 当作命令名/文件名查找（如 no such file or directory: VAR=...）；即命令经人工粘贴通道传输时换行或反斜杠续行被丢弃。

## Discriminator
错误信息中被当作可执行文件查找的 token 恰是原命令里的 env 赋值或行首参数，而非模块内部的 traceback/参数校验错误——这一事实在第一轮就已可见，足以把失败定位到词法/传输层，排除命令语义问题，也排除继续重试原格式或修改 CLI 参数的分支。

## Short path
- 由错误 token 判定失败层级：粘贴丢失了续行符，属传输层；修复对象是命令的发射格式，不是参数语义
- 补齐 CLI 签名这一未知量：用只读方式（总 usage 或 grep 源码 add_parser/add_argument）确认被 fence 子命令的必选参数；不对被 fence 的子命令做执行型 --help 探测
- 用只读子命令读取当前可变状态（如 deployment generation），确定 --expected-类状态参数的正确取值
- 核验历史上已造成拒绝的前提：git HEAD 是否已含目标修复、tracked worktree 是否干净
- 发出单行命令：env VAR=... <绝对路径解释器> -m 模块 子命令 + flags 全绝对路径；env 前缀使粘贴再变形时赋值串只被当成 env 的参数
- 交付后停止，等用户回贴执行输出再进入下一步操作

## Stop conditions
- 已发出一条无换行、无续行符、路径全绝对、且每个状态型参数都与刚完成的只读探针结果一致的命令
- 或发现某前提不满足（HEAD 不含修复/tracked worktree 脏）时，先解决前提，不发命令

## Verification
- 重读发出的行：确认无反斜杠续行、无内部换行、所有路径为绝对路径
- 将状态型参数与只读探针输出逐项对照（如 expected 值 == 探针读到的当前值）
- 确认未对被权限 fence 的子命令发起执行型探测，签名来自源码/总 usage

## Counterexamples
- 错误来自模块自身 traceback 或 argparse 参数校验失败（语义层问题）→ 单行化无效，应修参数或代码
- 命令由 agent 自己的工具通道执行、不经人工粘贴 → 多行可读格式反而更好，无需防粘贴变形
- 命令本质交互式或含无法展平的嵌套引号结构 → 应改为写脚本文件让用户执行，而非强行单行
- 命令无状态前提且幂等（如纯查询）→ 直接重发单行版即可，完整前提核验属过度
