---
title: sympy 中等实例 SWE 验证：P2P 文件级回归 + 反斜杠转义陷阱（11/12 通过）
scenario: SWE-bench 测 sympy（或类似 P2P 为文件级的数据集）时：验证策略须文件级回归 + 注意反斜杠转义。
root_cause: sympy 数据格式特殊（P2P 文件级拼接 + F2P 嵌套列表）；heredoc 反斜杠转义陷阱导致修复代码写入失败但脚本不报错；批量验证脚本 grep 同名测试定位不准。
solution: sympy SWE-bench 中等实例要点：① P2P 验证跑 F2P 所在文件全量（sympy 的 PASS_TO_PASS 是文件级全测试拼接串）；② FAIL_TO_PASS 用 ast.literal_eval 解析；③ heredoc 写含反斜杠代码（如 \\dagger）时用 chr(92) 拼接或先写文件再精确替换，避免转义破坏；④ 多步修改脚本每步独立 assert+写盘（防中途失败丢改动）；⑤ 文件级回归有 failed 时 stash 对比确认环境性（本次 13031 修复后失败数 6→3 证明修复有效）。
evidence: "2026-08-17/18 SWE-bench sympy 中等难度 12 实例（patch 1007-1427）：11/12 F2P 全部通过（13031 环境限制：SparseMatrix.zeros(0,n) 老代码不支持，测试前置无法构造）。P2P 文件级回归：11 个全过，3 个实例的 failed 经 stash 对比确认环境性。关键坑：① sympy 数据集 P2P 是\"文件级全测试拼接串\"（非单测试名），须跑整个文件；② FAIL_TO_PASS 是 ast.literal_eval 可解析的列表字符串；③ heredoc 写代码时反斜杠转义易错（\\dagger 变 \dagger），须用 chr(92) 或精确 repr 匹配；④ 多次\"修复未生效\"因脚本 assert 失败中断导致内存改动未写盘。"
tags: [SWE-bench, sympy, P2P文件级, 转义陷阱]
source: {}
status: active
created_at: "2026-08-18T00:37:08.612040+08:00"
updated_at: "2026-08-18T00:37:08.612040+08:00"
---