---
title: "判据迭代要\"可离线重判\"：答案必须落全量（answer_full），不能只留摘要"
scenario: 评测判据（谓词/语义口径）迭代时，若样本只存 200 字摘要，改一次判据就得重跑全部真实 LLM 样本（红线 108 条 × ~1.5 min ≈ 2.7 小时/轮）。判据往往要迭代好几轮 → 迭代成本被测量手段绑架。
root_cause: "存档设计只保存了展示所需的摘要，没保存\"可重新判定\"的完整输入 → 判据一改，唯一手段是重跑模型，测量迭代成本被 LLM 成本绑定。"
solution: "跑批器落盘完整答案（run_eval.py 的 answer_full 字段，2026-10-23 14:05 起）+ 离线重判工具（evals/rule_redline_v1/rejudge.py：同一批 checkpoint 换判据规格重算，输出主/参考/截断三口径 + Wilson CI + 分用例表）。当前性验证：grep -n \"answer_full\" scripts/run_eval.py 应看到落盘字段；python3 evals/rule_redline_v1/rejudge.py --checkpoint <ck> --spec recorded judge_spec_v3.json --out /tmp/x 应输出两档对照。注意：无 answer_full 的旧批次**不能**可靠重判（只有 200 字摘要），报告里必须标注。"
evidence: "evidence://v1/e7fcda5a4ef0d8af292c623aca87fd3fda4bd5faf332aac8e5e565c470f85836（重判工具产出同批两档对照：61.3% / 80.7%）。"
tags: [eval, 可复算, 方法论]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-23T14:59:27.175656+08:00"
updated_at: "2026-10-23T14:59:27.175656+08:00"
---