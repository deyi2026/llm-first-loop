---
title: shell 多行 printf 参数里含引号或行尾反斜杠会破坏引号配对：改单行 printf 或把逻辑写成 .py 脚本
scenario: "LFL 推广班次用 execute_command 的多行 printf（每行一个单引号包裹的参数 + 行尾 \ 续行）批量写台账与脚本，连续两次报 `/bin/sh: -c: line N: unexpected EOF while looking for matching ''`，参数里的中文双引号与行尾反斜杠让 shell 的引号配对判断失效；另一次 argv 模式只写到了 stdout，没进目标文件，导致台账前几行丢失、审计误报缺行。"
root_cause: ""
solution: 三种稳态写法：①把要写的内容全部放一行 printf（参数用空格分隔，单引号包裹），末尾 >> 追加；②需要引号配对复杂的替换逻辑时，写成 .py 脚本文件再执行（替换对逐条 assert 命中，漏改即报错退出）；③argv 模式只适合 stdout 输出，要落盘必须配合 shell 重定向，不要依赖它写文件。写完一律用 wc -l 与一次读回核对行数。
evidence: 本班两次 shell 引号错误回执；台账曾因覆盖写丢行导致 AUDIT FAIL（后补回 5 行编号行转为 AUDIT PASS）；docs/promotion/_d64_revise.py、_d64_refresh.py、_d64_pkg2c.py 三个脚本均按「assert 命中才写」模式工作
tags: [execute_command, shell 引号, 台账写入, 脚本化]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-06T08:33:30.966117+08:00"
updated_at: "2026-11-06T08:33:30.966117+08:00"
---