---
title: "正文里「共 N 行」这类自算计数必须与回执登记命令同口径：split(\"\n\") 比 wc -l 多 1（R5 随机抽 2 条实开来源复核抓出 5 处全错）"
scenario: "在 LFL 推广班次里写对外科普文，正文需要引用本仓库源码的「文件共 N 行」「第 N 行写着什么」作为可核出处。台账（ledger）逐条登记这些数值的出处，回执文件里也用脚本生成读数。初稿用 Python `Path(p).read_text().split(\"\n\")` 的元素个数当「总行数」，而回执里同一批文件有的用 `wc -l`、有的用 split 元素数，两种口径混用。"
root_cause: ""
solution: "凡是自己算出来的计数（行数、条数、文件数），口径必须与回执里登记该数值的命令完全一致：回执写 `wc -l < f` 就用 `wc -l` 的结果，不要用 `len(open(f).read().split(\"\n\"))`（对以换行结尾的文件恒多 1）。核对方法：把回执脚本里生成该计数的表达式，与正文引用它时隐含的口径逐条对齐；对「共 N 行」这类同时被 R5 台账登记的数值，发布前随机抽 2 条实开来源、用同一命令复跑一次。发现不符时，改正文 + 改回执 + 改台账 + 重跑 md2html/审计三件套，并在回执里追加「口径更正」段写明根因与逐文件真值；已发布的内容走编辑页补丁（Range 真选区 + Input.insertText），并按 RULE-AI-28 对修订版重新取一次发布准入。"
evidence: "2026-11-06 午班 d65：台账随机抽 2 条实开来源复核，抽样命中 methods/store.py「共 2269 行」，wc -l 实测 2268 → 复查发现 5 处（store.py 641、methods/store.py 2269、reference_injection.py 61、schedule_task_grant.py 161、execute_command.py 1313）全是 split 元素数口径，比 wc -l 多 1；safety.py 当时用 wc -l 记故正确。改正后逐条复验正文引用的全部行号（store.py 49/50/51/52/53/54/56/536、methods/store.py 3/4、reference_injection.py 3/4/25/28/29、schedule_task_grant.py 132、safety.py 1/3/4/6/126 及 8 条模式、execute_command.py 780/793/810）全部命中；编辑页 Range+Input.insertText 替换 6 处，新串各≥1、旧串各=0，二次 Rule28 准入 PASS 后重发，公网复验新串全命中旧串零命中。回执：docs/promotion/receipts/d65research/lfl_static_readings.txt [11]、20261106-daily65-public-verified-revision.json。"
tags: [promotion, R5, ledger, 口径一致性, wc -l, 发布后修订]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-06T14:03:30.502912+08:00"
updated_at: "2026-11-06T14:03:30.502912+08:00"
---