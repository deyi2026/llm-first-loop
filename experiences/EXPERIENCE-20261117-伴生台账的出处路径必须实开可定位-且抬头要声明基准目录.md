---
title: 伴生台账的出处路径必须实开可定位，且抬头要声明基准目录
scenario: d93 台账出处写成相对路径 `receipts/d93research/lfl_readings.json`（实际位于 docs/promotion/receipts/…），R2-B 审稿子代理按根相对路径与 docs/promotion/ 两种基准都未命中，报「无法实开核验出处文件真实存在」并列为 F8 缺口；另有一行出处只写「本班执行轨迹」这类无回执字段可核的断言，被判 P1。
root_cause: ""
solution: 台账抬头显式声明路径基准（「本台账所有 receipts/… 出处均相对 docs/promotion/」），每条出处写可实开的具体文件路径或回执字段名；对无回执字段可核的自述类断言（如「本班未发布任何新功能」「未提交 git commit」），在出处列标注「本班自述，无回执字段可核」，不要挂一个不支撑该断言的字段。
evidence: R2-B 子代理（subagent_fcce7800d87b）C11 P2a「台账第 14 行行格式与第 18 行起 receipts/ 路径…否则 F8 出处文件真实存在无法定位」+ C8 P1「台账第 110 行出处仅写本班执行轨迹」；处置见 docs/promotion/_d93_apply_r2b.py（新增抬头基准声明 + 拆分自述类断言）与 docs/promotion/20261117-daily-93-sources.md 第 3 行抬头。
tags: [推广班次, 台账, 出处, 审稿]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-17T09:26:35.398388+08:00"
updated_at: "2026-11-17T09:26:35.398388+08:00"
---