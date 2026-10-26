---
title: 中断续接发布：memory 是过程观察、不是事实源，先核线上回执再动手
scenario: "跨会话接续发布任务时，用户最新指令（\"继续发布刚才那篇没发布好的\"）与本地 memory（\"发布受阻、未发布\"）冲突。memory 停在失败时刻（11:52-12:23），而实际 12:58 已发布成功。若直接按 memory 继续走 confirm 阶段，会二次发布同一篇文章。"
root_cause: ""
solution: "中断后接续发布类任务，先取事实源再动手，三步：(1) 读 receipts/ 下同平台 *-local.json 的 phase 与 public_item_id；(2) 请求 m.toutiao.com/i<id>/info/v2/ 回读线上 title / content 长度 / img 数；(3) 用 CDP Runtime.evaluate 读作品管理页 innerText 确认状态与是否有重复副本。memory 是过程观察、落后于回执是常态。当前性验证：python3 -c 读 receipts/20261018-daily18-toutiao-local.json 的 phase 字段应为 \"published\"；再 curl m.toutiao.com/i7697849988696654362/info/v2/ 应回读出标题与 6 张 img。若将来重跑该链接已 404，说明文章被删，需重新评估而非假定已发布。"
evidence: "receipts/20261018-daily18-toutiao-local.json: phase=published, public_item_id=7697849988696654362, published_at=2026-10-18T12:58, public_readback=SUCCESS；本次核验 m.toutiao.com/i7697849988696654362/info/v2/ 回读 title 与列表一致、content 6718 字符、img x6、含创作声明与模板来源尾注、publish_time 1792298598(=2026-10-18 12:43)；CDP Runtime.evaluate 读作品管理页 innerText 含该标题+「10-18 12:43 已发布」，全列表仅此一条（无重复副本）。"
tags: [发布, 头条, 状态核验, 中断续接, 防重复发布]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-18T20:26:42.464376+08:00"
updated_at: "2026-10-18T20:26:42.464376+08:00"
supersedes: [EXPERIENCE-20261011-发布类任务收尾必须核验线上终态-url-不能以编辑器内状态收尾]
---