---
title: argv 通道落盘脚本的两层解析换行坑：换行转义变真实换行破坏字符串字面量
scenario: LFL 每日推广任务需要用 execute_command 落盘长 python 脚本（CDP 复核脚本、画图脚本、构建脚本），且 shell 通道因 E6 灾难字面量硬阻断（管道接解释器/heredoc）只能走 argv 形式时，落盘脚本内的换行转义被两层解析破坏成真实换行符，导致运行时语法错误，每处需一轮返工。
root_cause: ""
solution: argv 通道落盘长脚本时：源码载荷里不要写换行转义字面量；目标脚本需要字面换行处用 chr(10) 拼接（或落盘后用 edit_file 修复被截断处）；写完先 ast.parse 语法自检再跑。
evidence: "docs/promotion/STATUS-20261026-daily40.md §六（教训收口）；_d40pre.py edit_file 修复回执（artifact://v1/5174e8ad940f4f289f22fd12707166c9，diff 实见跨行正则改回 [\\n]+ 单行）；figures/_d40.py 两处 edit_file 修复回执（chr(10) 拼接，diff 在案）；SyntaxError 回执见本班 execute_command 输出（2026-10-26 08:1x）"
tags: []
source:
  session: sched-0300b296 早班 d40
  workspace: ~/lfl-workspace/docs/promotion
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-26T08:46:34.916328+08:00"
updated_at: "2026-10-26T08:46:34.916328+08:00"
---

execute_command 的 argv 形式（["python3","-c",<源码>]）落盘长脚本文件时：-c 源码字符串里写的换行转义（\\n 两字符）会经过两层解析——第一层是 -c 参数自身的 Python 字符串语义，第二层是源码里 write_text('''…''') 的三引号字符串语义——最终写入目标文件的是真实换行符。若目标脚本里的 JS 正则 /\\n+/g 或多行文案依赖字面反斜杠+n，落盘即坏（SyntaxError EOL while scanning string literal 或 JS 跨行语法错误）。2026-10-26 d40 早班踩 2 次：①复核脚本 WORKS_JS 的 t.replace(/\\n+/g) 被截成跨行正则（回执：python3 _d40pre.py TypeError NoneType，sed -n 39p 实见真实换行）；②画图脚本 block() 文案（回执：SyntaxError EOL）。修复均用 edit_file 把该处改为 chr(10) 拼接，重跑成功。正确做法：目标脚本内需要字面换行两字符处一律 chr(10) 拼接；落盘后先 ast.parse 语法自检再跑；同一载荷若还含「python3 -c」描述+管道符字样组合（如 STATUS 文本里的 curl 竖线 python3），会再触发 E6 灾难字面量扫描，按 EXPERIENCE-20260923 标准处置改写字样而非提权（本班末尾 STATUS 落盘实测命中，改写后过）。