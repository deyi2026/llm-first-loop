---
title: "markdown 表格单元格以解释器名开头（如 \"| node v24.18.0\"）会触发 execute_command E6 管道直连解释器硬阻断"
scenario: "用 execute_command + heredoc 写含 markdown 表格的分析文档时，表格某行单元格以解释器名开头（例如 \"| node v24.18.0 ✅\"、\"| python3 ...\"），命令被安全守卫判定为\"任意管道直连解释器执行\"，返回 [安全硬阻断] E6_CATASTROPHIC_HARD，连续两次重试（含去掉 echo/wc 管道）均被拦。"
root_cause: "execute_command 的灾难性行为检测器对命令字符串做模式匹配，把 markdown 表格里的 \"| node ...\" / \"| python3 ...\" 误判为 shell 管道直连解释器（pipe to interpreter）。管道符后紧跟解释器二进制名即命中，与是否真的构成执行管道无关；文档表格的行首分隔符 \"|\" 与 shell 管道符在文本层面不可区分。"
solution: "不要用 execute_command heredoc 写这类文档。改用规范写入路径：1) execute_command 用 printf 写一行占位符（无管道、无解释器字样）建文件；2) read_file(snapshot=true) 取 snapshot_ref；3) edit_file(old_string=占位符, new_string=全文, expected_snapshot_ref=snapshot_ref) 原子写入。edit_file 不走 shell 解析，不触发该守卫。"
evidence: "同一 heredoc 写入命令连续 2 次被拦，回执均为 \"[安全硬阻断][E6_CATASTROPHIC_HARD] ... 任意管道直连解释器执行\"（命令含 markdown 表格行 \"| node v24.18.0 ✅、pnpm 12.11.2 ...\"）；改用 printf 占位符 + edit_file(expected_snapshot_ref=artifact://v1/b9fdd7fa7709486e86f5b0420a4c6d13) 后写入成功，回执 \"[修改完成并已校验] 替换 1 处，变更 +191/-1 行\"。"
tags: [execute_command, 安全守卫, 误判, heredoc, edit_file, 写文档]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-01T07:31:30.973370+08:00"
updated_at: "2026-11-01T07:31:30.973370+08:00"
---