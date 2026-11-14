---
title: 分析文里的引用编号与章节交叉引用必须逐条机械核对
scenario: 写带编号引用和章节交叉引用的长分析文时，凭记忆写下的编号会错：本次把 GitHub 标成「引用 6」（实为引用 5），并写了不存在的「见 §5.3」（实际在附录 C）
root_cause: ""
solution: 落盘后跑一次机械核对：①列出全部章节标题确认被引用章节存在；②按编号统计每个引用在正文与附录的出现次数；③grep 全部〔…〕标记看有无孤儿编号。核对抓出 2 处错误，修正后再走审查
evidence: "evidence://v1/bf154398e8af4dadb57aa0dde8de6fc7; evidence://v1/a4fd954fc2e6409eb09b006316b8f8b5; evidence://v1/eff5dbcdc228411dba8fc10fa2ca9341"
tags: [analysis-doc, citation-check, self-review]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-14T13:38:17.212270+08:00"
updated_at: "2026-11-14T13:38:17.212270+08:00"
---
