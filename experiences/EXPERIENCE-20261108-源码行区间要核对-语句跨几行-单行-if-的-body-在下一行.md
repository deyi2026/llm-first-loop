---
title: 源码行区间要核对「语句跨几行」——单行 if 的 body 在下一行
scenario: "对外稿引用 LFL 仓库源码行号时，若所引语句是 `if <cond>: continue` 这种单行 if 语句，真正的判断体在下一行。本班 d71 第九节第三条原写「`if str(entry.get(\"status\")) != \"queued\": continue` 夹在中间（夹紧那一句在第 653 行）」，而该 if 在第 653 行、continue 在第 654 行；台账也写成 653。R5 全量实开复核时被抓出。"
root_cause: ""
solution: "引用「夹紧那一句」这类跨行判断时，先实开文件确认 if 头与 body 各在哪一行，正文写「第 X 行到第 Y 行这一段里，夹紧那一句在第 Z 行」，并让正文、审稿包、台账三处逐字一致；台账 src 行写成 `src/…py:起-止` 形式，才能被核对器机械核对行号一致性。"
evidence: 本班实证：R5 FULL SWEEP（receipts/d71-r5-sweep.json，58 行逐行实开）在 653 行处抓出 src 区间与源码实际不符；正文与台账同步改为「第 653 行到第 654 行」，复跑 sweep 58 行 0 失败。
tags: [promotion, source-citation, verification, r5]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-08T13:48:10.329829+08:00"
updated_at: "2026-11-08T13:48:10.329829+08:00"
supersedes: [EXPERIENCE-20261108-源码行区间要三处逐字一致-正文引用区间-审稿包原文区间-台账出处区间必须是同一段行号, EXPERIENCE-20261107-正文引用的源码行号必须实开核对-r5-随机抽样抓到行号漂移-tools-task-py-110-11]
---