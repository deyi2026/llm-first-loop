---
title: 分段读取的边界行会被截断成假空行——否定结论前必须连续覆盖被裁字段
scenario: 只读审稿时把长文件按行分段读取(1-426 / 427-479)，恰好在 426 行断开，导致该行只显示为「- 」而被我判为「空 bullet」，并据此得出「台账声明 110 行、实际只有 109 个带值行、台账缺行」的错误 REVISE 结论
root_cause: 分段读取在分段边界处截断该行文本，而该行恰好是需要裁决的字段；我又把「我没读到内容」直接当成了「内容为空」。
solution: 凡要下「某行是空的 / 某条记录不存在 / 行数对不上」这类否定性裁决：(1) 先定位该行所在的段落边界（标题行、声明行、首条 bullet 行），用算术钉死段落范围而非靠分段边界猜；(2) 对被裁字段所在段落做一次连续、不在目标行处断开的读取，必要时对整个段落做全覆盖；(3) 与包内程序化回执（如 ledger_data_rows / empty_bullet_lines / row_count_matches_decl）交叉核对；(4) 只有连续覆盖且无程序化回执反证时，才可下否定结论。
evidence: "复裁读到 426 行为完整行「- 第 16 行到第 17 行 | src/llm_loop/tools/builtin/escalation.py:16-17（…） | 2026-11-10 08:14:47 CST」；台账段 370-479 连续覆盖共 110 行且全部为非空 bullet；d76-ledger-recheck.json 回执 ledger_data_rows=110、ledger_declared_rows=110、row_count_matches_decl=true、empty_bullet_lines=[]、row_for_16_17 命中，与包内声明一致，上一轮 REVISE 被推翻。"
tags: [read-discipline, partial-coverage, review-adjudication, truncation-artifact]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-10T09:01:53.089596+08:00"
updated_at: "2026-11-10T09:01:53.089596+08:00"
---