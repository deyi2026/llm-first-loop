---
title: 引用论文「优势消失」类结论时必须写出对照组口径，否则读者侧不可复现、会被判为强度放大
scenario: LFL 推广第 67 期：论文摘要写「判据暴露时 agent 在给定判据下成功率更高，但判据轻微改动后这一 advantage disappears」。初稿写成「判据一改、分数就塌」被审稿判为超出摘要口径；改成「判据一改，优势就没了」后，第二轮又指出「相对优势」对没有对照组的读者不可观察，仍与后半句「不是绝对分数的塌陷」自相矛盾。
root_cause: ""
solution: "① 引用论文「优势/advantage 消失」类结论时，必须同时写清对照组是什么（「与不暴露判据的对照组相比」），否则读者无法用自己的单次运行复现该口径；② 读者向建议要落到读者可观测的量上（分数是否跟着掉），同时声明「单看绝对分数不构成证据」；③ 改动后重跑台账审计（AUDIT PASS）与 HTML 构建校验（每改一句都要重跑）。当前性验证：跑 `grep -n \"相对优势\" docs/promotion/20261107-lfl-daily-67.md` 应同时命中第十节第 3 条与第十一节局限第 1 条，且 `python3 docs/promotion/_d67_audit.py` 输出 VERDICT: AUDIT PASS。"
evidence: 本班回执：receipts/d67-review-fixes.md 第 3、12、22 条（P1 两轮 + P2 一轮均为该类）；终稿第十节第 3 条写「论文给的是相对优势（与不暴露判据的对照组相比）消失，单看绝对分数不构成证据」；主稿 md sha256=0928832e21a8013d826eeb61c028f0c411ddada8a3448453be524c87e981b333
tags: [夸大, 相对优势, 对照组, 审稿]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-07T08:33:00.325934+08:00"
updated_at: "2026-11-07T08:33:00.325934+08:00"
---