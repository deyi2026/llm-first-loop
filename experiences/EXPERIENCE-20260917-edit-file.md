---
title: 同文件多处 edit_file 必须串行：首个成功写入即失效其余快照引用
scenario: 同一次回复中并行提交多个 edit_file 修改同一文件（src/llm_loop/config.py 4 处默认值修改）
root_cause: ""
solution: "同文件多处编辑按\"read_file(snapshot=true) → edit_file → 重新 read_file → edit_file\"逐处串行推进；不同文件的编辑才可并行。"
evidence: "本会话回执：config.py 首批 4 个并行 edit_file 中 1 成功（receipt artifact://v1/8b7377b5cc584c1a9bb44a81f3222e78）+ 3 失败（\"版本冲突: 当前完整文件字节已不同于 expected_snapshot_ref；本次未写入\"）；随后 255a672f→c74546c2→0c8d75f9→f94a3a20 逐处串行全部成功（写后复读一致）。"
tags: [edit_file, snapshot, file-contract, tool-usage]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-17T20:13:09.932520+08:00"
updated_at: "2026-09-17T20:13:09.932520+08:00"
---

同一文件的多处修改必须串行执行：每次 read_file(snapshot=true) 取得的 expected_snapshot_ref 只对应当前字节版本，任一 edit_file 成功后文件 sha 立即变化，同批其余 edit 全部以"版本冲突"失败（本次 1 成功 + 3 冲突，随后逐处"读快照→改"全部成功）。并行 edit_file 只适用于不同文件。