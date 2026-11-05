---
method_id: heredoc-script-file-over-inline-sh-for-complex-shell-6b5524635a0e
name: heredoc-script-file-over-inline-sh-for-complex-shell
description: 当 exec 工具回执显示命令实际经 /bin/sh -c 执行时，任何超出扁平 && 链的逻辑（函数定义、嵌套 ( ) 子shell、多行逐条目比对）都不要内联发送：POSIX sh 方言与换行/引号改写会触发 syntax error near unexpected token，或更糟——grep 落空仍整体 exit 0，比对结果静默为空（假绿）。正确做法：用引号 heredoc 落盘成脚本文件、显式 bash 执行，脚本对每个条目打印 OK/FAIL 回执；脚本引用的标识符必须从本轮自己先前回执逐字复制（如归档目录全名），不得缩写或凭记忆重打。
aliases: sh -c 函数定义报语法错, 复杂shell写成脚本文件再跑, 内联命令 syntax error near unexpected token, heredoc 落盘临时脚本, shell 内联假绿 grep 落空, bash 脚本替代多行内联命令
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:936:2e4751f872a73f92e73e
evidence_refs: learning:learn:e1c6123eb2d3
created_at: 2026-11-05T17:07:19.896835+08:00
updated_at: 2026-11-05T17:07:19.896835+08:00
---
## Trigger
需要在单条 shell 命令里写函数定义、嵌套子shell、或多行逐条目循环比对，而 exec 回执标注 [exec_mode=shell]（实际经 /bin/sh -c 执行，非 bash）

## Discriminator
当时已可见的三件事实：① 本 run 内联回执曾报 /bin/sh: -c: line 0: syntax error near unexpected token ')'，证明通道是 POSIX sh 非 bash；② 同一 run 里 heredoc 落盘的 /tmp/*.sh、*.py 全部一次成功；③ 自己前一步归档回执已逐字打印每个目标全名标识（如 01-lfl-service-gen-experience-20261025），缩写成 01 再 grep 必然 No such file 且 exit 0 假绿。

## Short path
- 发送前判复杂度：超出扁平 && 链（含函数/子shell/逐条目回显比对）→ 不走内联
- cat > /tmp/x.sh <<'EOS'（引号 heredoc 防变量改写）落盘，首行 #!/bin/bash；脚本引用的路径/目录名从本轮先前回执逐字复制
- bash /tmp/x.sh 执行，脚本对每个条目显式 echo OK/FAIL 与计数，杜绝子命令落空仍 exit 0 的假绿
- 若内联已报 syntax error near unexpected token，不换措辞重试内联，直接转落盘脚本

## Stop conditions
- 脚本 exit 0 且输出含全部预期条目的逐项回实行（条数=目标清单长度）
- stderr 无 /bin/sh 语法错误、无 No such file or directory

## Verification
- 逐项回实行数与清单数一致；关键计数 before/after 对账（如 worktrees 175→160）
- 对每个被引用标识符回 grep/ls 一次，确认与本轮先前回执同名同拼法

## Counterexamples
- 扁平 cd X && git status 一类简单链内联即可，落盘是纯开销
- 回执 stderr 显示 bash: 而非 /bin/sh: 时，函数语法本可内联
- 一次性探测、语法错本身就是要看的信号时，快速内联试错更省
- 环境无 /tmp 写权限或工具不支持 heredoc 时只能内联
- 已确认通道是 bash 且无引号改写风险时，勿机械套用
