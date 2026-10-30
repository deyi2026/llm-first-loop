---
title: echo 落盘内嵌 JS 的脚本：&&/|| 不可写成 \&\&/\|\|，长 JS 走独立 .js 文件，CDP 异常检测路径别写错
scenario: 通过 execute_command echo 单引号逐行落盘 CDP 自动化 python 脚本（内嵌 Runtime.evaluate JS）的任何班次/任务。
root_cause: ""
solution: JS 与运算符不转义；长 JS 走独立 .js 文件由 python 读取；CDP evaluate 包装的异常检测路径写对（result.exceptionDetails）并输出完整 description。
evidence: "本会话 20:5x-21:5x 多轮回执：_img45.py FIND_IMG_BTN 行 \&\& 字面量（read_file 快照可见）、_tag6/_tag10 建议 JS SyntaxError 回执（Invalid or unexpected token / missing ) after argument list）、修复后 AT:图49｜… 命中回执；_anchor45.js/_sugg2.js 独立文件方案一次通过"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T20:48:23.025140+08:00"
updated_at: "2026-10-30T20:48:23.025140+08:00"
---

2026-10-30 晚班发知乎过程中，用 echo 单引号逐行落盘 python 脚本（规避 E6 的合规写法）时，脚本内嵌 JS 的逻辑与运算符写成 \&\& 与 \|\|（习惯性转义），echo 单引号内反斜杠原样落盘，Runtime.evaluate 收到 \& 非法转义直接 SyntaxError: Invalid or unexpected token；且 zh.py 风格的 ev() 若异常检测键路径写错（exceptionDetails 在 r["result"] 下而非顶层 r），异常会被吞成 None，误判为"元素未找到"而非"JS 语法错"，把排查引向 DOM 选择器方向。当日命中 4 次（anchor JS、FIND_IMG_BTN、话题建议查询、CHECK 查询），每次浪费 1-2 轮。运作规则：①echo 落盘含 JS 的脚本时，&&/|| 一律不转义（单引号内无需转义，转义反而落盘字面反斜杠）；②长 JS 一律走独立 .js 文件（echo 直接写，天然无转义歧义），python 只负责读取与拼接锚点参数；③CDP evaluate 包装函数的异常检测必须查 r.get("result",{}).get("exceptionDetails")，并把 description 全文带出（只取 text 字段会丢 SyntaxError 详情）。