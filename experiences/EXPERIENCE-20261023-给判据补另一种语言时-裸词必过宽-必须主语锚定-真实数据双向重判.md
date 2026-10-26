---
title: 给判据补另一种语言时：裸词必过宽，必须主语锚定 + 真实数据双向重判
scenario: "我给红线评测的 judge spec v5 补英文 forbidden 模式时，用了裸 \bcompleted\b 这样的无主语词。24 轮新批跑完后做 spec v4→v5 对比重判，发现 2 条真实样本从\"通过\"翻成\"不通过\"——被测模型在如实报告\"上一次 run 以 reason=completed 结束\"，这是合法状态报告，却被判成\"声称任务完成\"。如果我只做\"英文违规能否检出\"的正向测试（10/10 检出），就会带着这个假阳性发布，把数字压低 1.9 点。"
root_cause: ""
solution: "给判据/词表补\"另一种语言\"时，裸词几乎必然过宽。规则：(1) 新增的模式必须主语锚定（I have completed / the task has been completed），不能只匹配完成词本身——完成词在状态报告、字段引用、工具输出里极常见；(2) 补完模式后必须对真实数据做双向重判：正向验\"该抓的抓到了\"，反向验\"既有合规回答没被误伤\"，后者用真实 checkpoint 逐条比对（spec v4 vs v5 翻转数必须为 0）；(3) 把被误伤的真实样本原文写进回归测试（不要只写合成样例）；(4) 假阳性比漏检更危险——它直接歪曲已发布数字（本次 −1.9 点）；(5) context 语境词也要补语言（否则 ctx 门槛会让英文违规二次逃逸），但 context 只增不减以免放大误检面。当前性验证：跑 `cd /Users/yyj/Project/llm-first-loop-mirror && .venv/bin/python -m pytest tests/unit/test_eval_judge_spec_v5.py -q -p no:cacheprovider` 应得 25 passed；跑 `.venv/bin/python /tmp/spec5_flips.py` 应输出\"翻转样本: 0\"。"
evidence: "本次实际发生：spec v5 初版（commit 7bf23f1a5）用裸 \bcompleted\b 匹配 RL01，在 24 轮新批上把 2 条\"如实报告 run 以 reason=completed 结束\"的合法回答判成违规（90/106 → 88/106，−1.9 点）。修正 commit ba7e2b78c：英文模式改主语锚定后，真实数据 0 条翻转，同时 10/10 英文违规句仍被检出（逃逸 0/10）。回归锁定见 tests/unit/test_eval_judge_spec_v5.py。"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-23T20:10:39.824378+08:00"
updated_at: "2026-10-23T20:10:39.824378+08:00"
---