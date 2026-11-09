---
title: 台账的 src 行必须带行号——否则放弃「三处行区间逐字一致」的机械核对
scenario: R5 写前量化台账若只写源码相对路径（如 src/llm_loop/introspection/lane_gate.py），核对器无法机械核对「正文引用的行区间 / 审稿包给的原文区间 / 台账出处区间」三处一致，只能靠人眼。本班 d71 台账第一版就是纯路径，等于放弃了这条机械检查。
root_cause: ""
solution: "台账 src 行统一写成 `src/…py:起-止`，让核对器能逐条断言：文件存在、行区间在界内、行号与出处一致、区间内含证据串；这样「正文写错行号」这类错误才会在发布前被自动抓出，而不是等公网读者发现。"
evidence: "d71：台账 20261108-daily-71-sources.md 共 58 行，src 行全部为 `路径:起-止` 格式；核对器 _d71_r5_sweep.py 据此逐行实开，58 行 0 失败，并抓出 653/654 行号错误（见 receipts/d71-r5-sweep.json）。"
tags: [promotion, r5, ledger, verification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-08T13:48:10.719026+08:00"
updated_at: "2026-11-08T13:48:10.719026+08:00"
supersedes: [EXPERIENCE-20261107-r5-台账核对不能停在随机抽-2-条-台账行数不大时应全量逐行实开复核-且核对器要按断言类型分派]
---