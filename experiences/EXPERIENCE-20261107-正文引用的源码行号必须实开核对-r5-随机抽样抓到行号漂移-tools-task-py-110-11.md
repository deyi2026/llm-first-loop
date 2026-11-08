---
title: "正文引用的源码行号必须实开核对——R5 随机抽样抓到行号漂移（tools_task.py:110-113 → 118-122）"
scenario: "LFL 推广第 67 期：正文第九节引用 LFL 源码字段位置，写成 `src/llm_loop/introspection/tools_task.py:110-113`，台账与图 293 也照抄该行号。R5 随机抽 2 条实开来源复核时，样本 2 实开该文件发现 110-113 行其实是状态枚举字段，真正的 acceptance/done_when 说明在 118-122 行——行号整体漂移，正文论断本身没错但定位错了。"
root_cause: ""
solution: "① 正文引用源码行号前一律实开核对（sed -n 'A,Bp' 或 awk 'NR>=A && NR<=B'），行号抄进正文后，台账与配图三处要同步改，避免正文对了图注错；② 把「实开源码行」作为 R5 随机抽样的固定候选之一，与论文摘要原文并列；③ 行号漂移不必重写论点，只需改正定位并重跑台账审计（AUDIT PASS）与 HTML 构建校验。当前性验证：跑 `sed -n '118,122p' src/llm_loop/introspection/tools_task.py` 应看到 \"acceptance\" 与 \"done_when\" 两行说明；若仓库改动后行号漂移，应重跑 `python3 docs/promotion/_d67_r5_pick2.py` 复核对。"
evidence: "本班回执：receipts/d67-r5-pick2.json（sample 2 checks 全 false → 修正后 PASS）；修正前正文/台账/配图三处均写 tools_task.py:110-113，实际 awk 'NR>=117 && NR<=123' 显示 acceptance/done_when 在 118-122 行；STATUS-20261107-daily67.md 第四节与第七节第 2 条已登记"
tags: [行号, 源码, R5, 核对]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-07T08:32:47.416843+08:00"
updated_at: "2026-11-07T08:32:47.416843+08:00"
supersedes: [EXPERIENCE-20261106-正文里-共-n-行-这类自算计数必须与回执登记命令同口径-split-n-比-wc-l-多-1-r5]
---