---
title: 审稿闭环失控的根因与停止规则：改 P2→换 SHA→旧 PASS 失效→必须全量复审（P0/P1 恒为 0 却跑 10 轮）
scenario: LFL 推广午班 2026-11-12（d80）写稿→审稿→改稿→复审循环中，审稿轮数失控（10 轮审稿子代理 / 39 条措辞级 P2 / 稿件改版 7 版 / 重贴 7 次），耗时远超必要。
root_cause: 审稿闭环缺少停止规则与 P2 分级：把「任何 P2 都必须处置」当成硬要求，而处置 P2 必然改稿、改稿必然换 SHA、换 SHA 必然使旧 PASS 失效、旧 PASS 失效必然要求重新全量审稿。四个环节各自看都合理，串起来就是一个不收敛的循环；再叠加审稿包只放摘要要点清单，制造了「假 P2」来火上浇油（改完仍会被下一轮挑出新措辞问题）。
solution: ① P2 分级：只有 (a) 改变事实口径 (b) 违反标题/标签规范 (c) 触发「未测防护写成已验证」「区间端点放大成单值」两类夸大 (d) 事实错误——这四类 P2 强制处置并复审；其余措辞级 P2 一次性汇总成「未修清单」随 STATUS 落盘，不阻断发布。② 轮数上限 2 轮：第 1 轮处置全部 P0/P1 + 事实类 P2；第 2 轮窄复审后立即冻结定稿；第 3 轮起只接受 P0/P1。③ 窄复审：复审包只送「改动行 + 改动原因 + 相邻上下文」，不重复送 26.8K 全量正文（成本约 1/5）。④ 审稿包必须放论文完整 summary 原文，不放要点清单——否则审稿人会把「摘要有据」误判成「摘要无依据」，凭空多出一轮复审。⑤ 改稿后重新出包时，审稿 prompt 里写死的数字/章节号每轮都要订正（既有卡）。预期：单班审稿轮数从 10 轮降到 2–3 轮，改稿从 7 版降到 2–3 版。
evidence: "证据：docs/promotion/receipts/daily80-toutiao-local.json（7 个 md SHA：19db82ac/a0d98905/86371bbf/4d6b0967/b59cdcf7/dc8ecd8b/554d4c1d，对应 7 次 clear+pasted）；docs/promotion/STATUS-20261112-daily80.md §八.1 与 §九.1–§九.4；docs/promotion/receipts/d80-review-pkg-A1.md / d80-review-pkg-B.md（包体只含要点清单）；docs/promotion/STATUS-20261112-daily80.md §八.2（4 处假阳性原文摘录）；docs/promotion/receipts/d80-poll-final.json（14:34→14:44:10，审核 9 分 39 秒）"
tags: [promotion, toutiao, review-loop, p2-triage, stop-rule, narrow-rereview, arxiv, fact-check]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-12T15:19:36.732642+08:00"
updated_at: "2026-11-12T15:19:36.732642+08:00"
supersedes: [EXPERIENCE-20261026-文稿独立审查闭环-每修订一轮就换-sha-pass-回执必须重新覆盖当前产物]
---

scenario: LFL 推广午班 2026-11-12（d80）。写了 12.7K 字符长文 + 5 图 + 113 行台账。首轮审稿（A1 论文事实专项）判 PASS，P0=0、P1=0，只提出 5 条措辞级 P2（“摘要未列‘多个主流 LLM 后端’”“‘交易类任务’摘要无据”等）。

solution: 我逐条处置 P2 → 改稿 → md SHA 变化 → 旧 PASS 不覆盖新产物 → 必须重新出包复审 → 复审又提出新的措辞级 P2 → 再改稿。形成闭环，最终跑了 10 轮审稿子代理（A1×5、A2×3、B×2），累计 39 条 P2，稿件改版 7 次（7 个不同 md SHA），编辑器重贴 7 次（每次含 5 图 data-URI 重注入）。14:34 提交、14:44 转已发布，审核仅 9 分 39 秒——**平台侧完全正常，耗时全在审稿闭环**。

关键误判（4 处假阳性）：审稿包只放了摘要「要点清单」而非完整 summary 原文，审稿人看不到 “leading LLM backbones” / “information-seeking and transactional tasks” / “matches on recall” / “unfinished files, outdated versions, and failed attempts” 这几句，就把有据的表述判成「摘要无依据」。我实开 arXiv 完整 summary 核对后确认是包的问题，不是稿的问题。

适用边界：只适用于「P0/P1 已为 0、剩余全是措辞级 P2」的情形；只要出现 P0/P1 或事实口径类 P2，仍必须改稿并复审。