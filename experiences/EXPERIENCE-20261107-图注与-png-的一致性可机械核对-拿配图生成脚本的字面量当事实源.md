---
title: 图注与 PNG 的一致性可机械核对：拿配图生成脚本的字面量当事实源
scenario: LFL 推广班次的图文配图审阅（d68 午班 2026-11-07）：审稿子代理指出「PNG 未随审稿包提供，alt 与图内文字无法逐字核」，要求补核；且图注与图内文字口径漂移（图294 图注写「作者自报，本文未复现」，图295/296 没有）靠人眼比对不可靠。
root_cause: ""
solution: 配图由生成脚本（figures/_dNN.py）绘制时，图上文字就是脚本里的字面量——据此把「图注断言 ↔ 图内文字」写成可判定的字符串包含关系：①对每张图取脚本里对应段落，②定义该图应当出现的断言列表（论文 ID、每个数值、关键标签名），逐条查是否出现在该段落，③反向查「图注里出现但图上没有」的数值集合（用 alt 抽数字 ∩ 段落数字做差）。断言清单写成「标签+数值」成对，避免整句措辞差异造成假阴性。
evidence: "本班已落地为 docs/promotion/_d68_caption_check.py，产出 receipts/d68-caption-check.json：4 张图（fig294–297）断言全中、图注有而图上没有的数值 0 个 → CAPTION CHECK PASS。该检查同时把图294 的图注措辞与 PNG 内文字对齐成逐字一致（\"FPR=0.05 时的 TPR 为 0.74\"）。"
tags: [LFL推广, 配图, 图注核对, 机械核对]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-07T13:44:53.745409+08:00"
updated_at: "2026-11-07T13:44:53.745409+08:00"
---